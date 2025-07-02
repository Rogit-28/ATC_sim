/**
 * ATC Simulator — three.js 3D Radar Scene
 *
 * Manages the 3D scene: ground plane, grid, runways, aircraft markers,
 * labels, trails, and camera controls.
 */

/* global THREE */

class RadarScene {
    constructor(canvas) {
        this.canvas = canvas;
        this.aircraftMeshes = new Map(); // id -> { mesh, label, trail }
        this.trailPoints = new Map();    // id -> position array
        this.showLabels = true;
        this.showTrails = true;
        this.altitudeFilter = 0;

        // Scale: 1 three.js unit = 1 km
        this.SCALE = 1.0;
        this.FT_TO_KM = 0.0003048;

        this._initScene();
        this._initCamera();
        this._initLights();
        this._initGround();
        this._initGrid();
        this._initControls();
        this._initRunways();

        // Raycaster for hover/click
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        // Start render loop
        this._animate = this._animate.bind(this);
        this._animate();
    }

    _initScene() {
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0a0e17);
        this.scene.fog = new THREE.Fog(0x0a0e17, 150, 300);

        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            antialias: true,
            alpha: false,
        });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this._resize();
        window.addEventListener('resize', () => this._resize());
    }

    _initCamera() {
        const aspect = this.canvas.clientWidth / this.canvas.clientHeight;
        this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 500);
        this.camera.position.set(0, 80, 120);
        this.camera.lookAt(0, 0, 0);
    }

    _initLights() {
        const ambient = new THREE.AmbientLight(0x334466, 0.6);
        this.scene.add(ambient);

        const directional = new THREE.DirectionalLight(0xffffff, 0.8);
        directional.position.set(50, 100, 50);
        this.scene.add(directional);

        // Subtle hemisphere for depth
        const hemi = new THREE.HemisphereLight(0x2244aa, 0x111122, 0.3);
        this.scene.add(hemi);
    }

    _initGround() {
        // Dark ground plane
        const groundGeo = new THREE.PlaneGeometry(200, 200);
        const groundMat = new THREE.MeshLambertMaterial({
            color: 0x0d1117,
            transparent: true,
            opacity: 0.9,
        });
        this.ground = new THREE.Mesh(groundGeo, groundMat);
        this.ground.rotation.x = -Math.PI / 2;
        this.ground.position.y = -0.1;
        this.scene.add(this.ground);
    }

    _initGrid() {
        // Sector boundary grid (200km x 200km, centered at origin)
        const gridHelper = new THREE.GridHelper(200, 40, 0x1a2744, 0x131c30);
        gridHelper.position.y = 0;
        this.scene.add(gridHelper);

        // Sector boundary box outline
        const boxGeo = new THREE.BoxGeometry(200, 15, 200);
        const edges = new THREE.EdgesGeometry(boxGeo);
        const line = new THREE.LineSegments(
            edges,
            new THREE.LineBasicMaterial({ color: 0x2a3a5c, transparent: true, opacity: 0.5 })
        );
        line.position.y = 7.5;
        this.scene.add(line);

        // Range rings (every 25km)
        for (let r = 25; r <= 100; r += 25) {
            const ringGeo = new THREE.RingGeometry(r - 0.05, r + 0.05, 64);
            const ringMat = new THREE.MeshBasicMaterial({
                color: 0x1a2744,
                side: THREE.DoubleSide,
                transparent: true,
                opacity: 0.4,
            });
            const ring = new THREE.Mesh(ringGeo, ringMat);
            ring.rotation.x = -Math.PI / 2;
            ring.position.y = 0.01;
            this.scene.add(ring);
        }
    }

    _initControls() {
        this.controls = new THREE.OrbitControls(this.camera, this.canvas);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.08;
        this.controls.maxPolarAngle = Math.PI / 2.1;
        this.controls.minDistance = 10;
        this.controls.maxDistance = 250;
        this.controls.target.set(0, 0, 0);
    }

    _initRunways() {
        // Visual runway representations (matching main.py defaults)
        const runways = [
            { pos: [0, 0], heading: 40, length: 3.46 },
            { pos: [1.5, -0.5], heading: 130, length: 3.05 },
            { pos: [-0.5, 1.0], heading: 220, length: 2.56 },
            { pos: [-1.0, 0.5], heading: 310, length: 4.42 },
        ];

        runways.forEach(rwy => {
            const len = rwy.length;
            const geo = new THREE.BoxGeometry(0.3, 0.05, len);
            const mat = new THREE.MeshLambertMaterial({ color: 0x555555 });
            const mesh = new THREE.Mesh(geo, mat);

            // Convert heading to radians (runway heading is true north clockwise)
            const rad = -(rwy.heading * Math.PI / 180);
            mesh.rotation.y = rad;
            mesh.position.set(rwy.pos[0], 0.02, rwy.pos[1]);
            this.scene.add(mesh);

            // Runway center light
            const lightGeo = new THREE.BoxGeometry(0.15, 0.08, len * 0.8);
            const lightMat = new THREE.MeshBasicMaterial({
                color: 0x22c55e,
                transparent: true,
                opacity: 0.4,
            });
            const lightMesh = new THREE.Mesh(lightGeo, lightMat);
            lightMesh.rotation.y = rad;
            lightMesh.position.set(rwy.pos[0], 0.05, rwy.pos[1]);
            this.scene.add(lightMesh);
        });

        // Airport center marker
        const markerGeo = new THREE.CircleGeometry(2, 32);
        const markerMat = new THREE.MeshBasicMaterial({
            color: 0x3b82f6,
            transparent: true,
            opacity: 0.15,
            side: THREE.DoubleSide,
        });
        const marker = new THREE.Mesh(markerGeo, markerMat);
        marker.rotation.x = -Math.PI / 2;
        marker.position.y = 0.01;
        this.scene.add(marker);
    }

    // -----------------------------------------------------------------
    // Aircraft management
    // -----------------------------------------------------------------

    updateAircraft(aircraftArray) {
        const activeIds = new Set();

        for (const ac of aircraftArray) {
            activeIds.add(ac.id);

            // Convert position: sim uses [x, y, z] in km, z = altitude in km
            // three.js: x = sim.x, y = sim.z (altitude), z = sim.y
            const x = ac.p[0];
            const y = ac.p[2]; // altitude in km
            const z = ac.p[1];

            // Altitude filter
            const altFt = ac.a;
            if (altFt < this.altitudeFilter) {
                this._removeAircraftMesh(ac.id);
                continue;
            }

            if (this.aircraftMeshes.has(ac.id)) {
                this._updateAircraftMesh(ac.id, ac, x, y, z);
            } else {
                this._createAircraftMesh(ac.id, ac, x, y, z);
            }
        }

        // Remove aircraft no longer in the data
        for (const [id] of this.aircraftMeshes) {
            if (!activeIds.has(id)) {
                this._removeAircraftMesh(id);
            }
        }
    }

    _createAircraftMesh(id, ac, x, y, z) {
        // Aircraft marker — cone pointing in heading direction
        const geo = new THREE.ConeGeometry(0.4, 1.2, 4);
        geo.rotateX(Math.PI / 2);

        const color = this._getAircraftColor(ac);
        const mat = new THREE.MeshLambertMaterial({ color });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(x, y, z);

        // Rotate to heading (heading is degrees from north, clockwise)
        const headingRad = -(ac.h * Math.PI / 180) + Math.PI / 2;
        mesh.rotation.y = headingRad;

        mesh.userData = { aircraftId: id };
        this.scene.add(mesh);

        // Vertical drop line (from aircraft to ground)
        const lineGeo = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(x, 0, z),
            new THREE.Vector3(x, y, z),
        ]);
        const lineMat = new THREE.LineBasicMaterial({
            color: 0x3b82f6,
            transparent: true,
            opacity: 0.2,
        });
        const dropLine = new THREE.Line(lineGeo, lineMat);
        this.scene.add(dropLine);

        // Label sprite
        const label = this._createLabel(ac.cs, altFtStr(ac.a));
        label.position.set(x, y + 1.2, z);
        label.visible = this.showLabels;
        this.scene.add(label);

        // Trail init
        this.trailPoints.set(id, []);

        this.aircraftMeshes.set(id, { mesh, label, dropLine, trail: null });
    }

    _updateAircraftMesh(id, ac, x, y, z) {
        const obj = this.aircraftMeshes.get(id);
        if (!obj) return;

        // Smooth position interpolation
        obj.mesh.position.lerp(new THREE.Vector3(x, y, z), 0.3);

        // Update heading
        const headingRad = -(ac.h * Math.PI / 180) + Math.PI / 2;
        obj.mesh.rotation.y = headingRad;

        // Update color
        const color = this._getAircraftColor(ac);
        obj.mesh.material.color.setHex(color);

        // Update drop line
        const positions = obj.dropLine.geometry.attributes.position;
        if (positions) {
            positions.setXYZ(0, obj.mesh.position.x, 0, obj.mesh.position.z);
            positions.setXYZ(1, obj.mesh.position.x, obj.mesh.position.y, obj.mesh.position.z);
            positions.needsUpdate = true;
        }

        // Update label
        if (obj.label) {
            obj.label.position.set(
                obj.mesh.position.x,
                obj.mesh.position.y + 1.2,
                obj.mesh.position.z
            );
            obj.label.visible = this.showLabels;
            this._updateLabelText(obj.label, ac.cs, altFtStr(ac.a));
        }

        // Trail management
        if (this.showTrails) {
            this._updateTrail(id, obj.mesh.position.clone());
        }
    }

    _removeAircraftMesh(id) {
        const obj = this.aircraftMeshes.get(id);
        if (!obj) return;

        this.scene.remove(obj.mesh);
        obj.mesh.geometry.dispose();
        obj.mesh.material.dispose();

        if (obj.label) {
            this.scene.remove(obj.label);
            if (obj.label.material.map) obj.label.material.map.dispose();
            obj.label.material.dispose();
        }

        if (obj.dropLine) {
            this.scene.remove(obj.dropLine);
            obj.dropLine.geometry.dispose();
            obj.dropLine.material.dispose();
        }

        if (obj.trail) {
            this.scene.remove(obj.trail);
            obj.trail.geometry.dispose();
            obj.trail.material.dispose();
        }

        this.trailPoints.delete(id);
        this.aircraftMeshes.delete(id);
    }

    _updateTrail(id, position) {
        let points = this.trailPoints.get(id);
        if (!points) {
            points = [];
            this.trailPoints.set(id, points);
        }

        points.push(position);

        // Max 60 trail points (~6 seconds at 10Hz)
        if (points.length > 60) points.shift();

        const obj = this.aircraftMeshes.get(id);
        if (!obj) return;

        // Remove old trail
        if (obj.trail) {
            this.scene.remove(obj.trail);
            obj.trail.geometry.dispose();
            obj.trail.material.dispose();
        }

        if (points.length < 2) return;

        const trailGeo = new THREE.BufferGeometry().setFromPoints(points);
        const trailMat = new THREE.LineBasicMaterial({
            color: 0x3b82f6,
            transparent: true,
            opacity: 0.35,
        });
        obj.trail = new THREE.Line(trailGeo, trailMat);
        this.scene.add(obj.trail);
    }

    _getAircraftColor(ac) {
        if (ac.em) return 0xef4444;    // Emergency — red
        switch (ac.st) {
            case 'HOLDING':    return 0xf97316;  // Orange
            case 'APPROACH':   return 0x22c55e;  // Green
            case 'LANDING':    return 0x22c55e;
            case 'DESCENDING': return 0xeab308;  // Yellow
            case 'DIVERTED':   return 0xef4444;  // Red
            case 'CRUISING':
            default:           return 0x3b82f6;  // Blue
        }
    }

    _createLabel(callsign, altStr) {
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 64;
        const ctx = canvas.getContext('2d');

        ctx.fillStyle = 'rgba(10, 14, 23, 0.7)';
        ctx.fillRect(0, 0, 256, 64);

        ctx.font = 'bold 20px monospace';
        ctx.fillStyle = '#06b6d4';
        ctx.fillText(callsign, 8, 24);

        ctx.font = '16px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(altStr, 8, 48);

        const texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;

        const mat = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false,
        });
        const sprite = new THREE.Sprite(mat);
        sprite.scale.set(4, 1, 1);
        sprite.userData._canvas = canvas;
        sprite.userData._ctx = ctx;
        return sprite;
    }

    _updateLabelText(sprite, callsign, altStr) {
        const ctx = sprite.userData._ctx;
        if (!ctx) return;

        ctx.clearRect(0, 0, 256, 64);
        ctx.fillStyle = 'rgba(10, 14, 23, 0.7)';
        ctx.fillRect(0, 0, 256, 64);

        ctx.font = 'bold 20px monospace';
        ctx.fillStyle = '#06b6d4';
        ctx.fillText(callsign, 8, 24);

        ctx.font = '16px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(altStr, 8, 48);

        sprite.material.map.needsUpdate = true;
    }

    // -----------------------------------------------------------------
    // Camera
    // -----------------------------------------------------------------

    resetCamera() {
        this.camera.position.set(0, 80, 120);
        this.controls.target.set(0, 0, 0);
        this.controls.update();
    }

    // -----------------------------------------------------------------
    // Raycast (for hover)
    // -----------------------------------------------------------------

    getAircraftAtScreen(clientX, clientY) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);

        const meshes = [];
        for (const [, obj] of this.aircraftMeshes) {
            meshes.push(obj.mesh);
        }

        const intersects = this.raycaster.intersectObjects(meshes);
        if (intersects.length > 0) {
            return intersects[0].object.userData.aircraftId;
        }
        return null;
    }

    // -----------------------------------------------------------------
    // Render loop
    // -----------------------------------------------------------------

    _resize() {
        const parent = this.canvas.parentElement;
        const w = parent.clientWidth;
        const h = parent.clientHeight;

        this.renderer.setSize(w, h);
        if (this.camera) {
            this.camera.aspect = w / h;
            this.camera.updateProjectionMatrix();
        }
    }

    _animate() {
        requestAnimationFrame(this._animate);
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    // -----------------------------------------------------------------
    // Cleanup
    // -----------------------------------------------------------------

    dispose() {
        for (const [id] of this.aircraftMeshes) {
            this._removeAircraftMesh(id);
        }
        this.renderer.dispose();
    }
}

// Utility
function altFtStr(ft) {
    if (ft >= 10000) return 'FL' + Math.round(ft / 100);
    return Math.round(ft) + 'ft';
}
