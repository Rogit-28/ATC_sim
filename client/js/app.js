/**
 * ATC Simulator — Main Application Controller
 *
 * Wires together the 3D scene, WebSocket client, and UI controls.
 */

/* global RadarScene, ATCWebSocket */

(function () {
    'use strict';

    // -----------------------------------------------------------------
    // DOM references
    // -----------------------------------------------------------------
    const canvas = document.getElementById('radar-canvas');
    const simStatus = document.getElementById('sim-status');
    const simTime = document.getElementById('sim-time');
    const tickCounter = document.getElementById('tick-counter');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const wsIndicator = document.getElementById('ws-indicator');
    const aircraftList = document.getElementById('aircraft-list');
    const aircraftCountBadge = document.getElementById('aircraft-count-badge');
    const altitudeFilter = document.getElementById('altitude-filter');
    const altitudeFilterValue = document.getElementById('altitude-filter-value');
    const showLabels = document.getElementById('show-labels');
    const showTrails = document.getElementById('show-trails');
    const showConflicts = document.getElementById('show-conflicts');
    const btnResetCamera = document.getElementById('btn-reset-camera');
    const tooltip = document.getElementById('aircraft-tooltip');

    // Stat elements
    const statAircraft = document.getElementById('stat-aircraft');
    const statConflicts = document.getElementById('stat-conflicts');
    const statHolding = document.getElementById('stat-holding');
    const statApproach = document.getElementById('stat-approach');
    const statLanded = document.getElementById('stat-landed');
    const statDiverted = document.getElementById('stat-diverted');

    // -----------------------------------------------------------------
    // Initialize
    // -----------------------------------------------------------------
    const scene = new RadarScene(canvas);
    const ws = new ATCWebSocket();

    // Last frame data for UI
    let lastFrame = null;
    let lastAircraftArray = [];

    // -----------------------------------------------------------------
    // WebSocket callbacks
    // -----------------------------------------------------------------
    ws.onFrame((frame) => {
        lastFrame = frame;
        lastAircraftArray = frame.a || [];

        // Update 3D scene
        scene.updateAircraft(lastAircraftArray);

        // Update stats
        updateStats(frame);

        // Update aircraft list (throttled)
        throttledUpdateList(lastAircraftArray);
    });

    ws.onConnect(() => {
        wsIndicator.className = 'ws-dot connected';
        wsIndicator.title = 'WebSocket: Connected';
    });

    ws.onDisconnect(() => {
        wsIndicator.className = 'ws-dot disconnected';
        wsIndicator.title = 'WebSocket: Disconnected';
    });

    // Connect immediately
    ws.connect();

    // -----------------------------------------------------------------
    // Stats update
    // -----------------------------------------------------------------
    function updateStats(frame) {
        // Sim time
        const totalSec = Math.floor(frame.t || 0);
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        simTime.textContent = `T+${h}:${pad(m)}:${pad(s)}`;
        tickCounter.textContent = `Tick: ${frame.k || 0}`;

        // Stats cards
        const stats = frame.s || {};
        statAircraft.textContent = frame.n || 0;
        statConflicts.textContent = stats.conflicts || 0;
        statHolding.textContent = stats.holding || 0;
        statApproach.textContent = stats.approach || 0;
        statLanded.textContent = stats.landed || 0;
        statDiverted.textContent = stats.diverted || 0;

        // Conflict highlighting
        if (stats.conflicts > 0) {
            statConflicts.parentElement.style.borderColor = '#ef4444';
        } else {
            statConflicts.parentElement.style.borderColor = '';
        }
    }

    // -----------------------------------------------------------------
    // Aircraft list (throttled to ~2 Hz)
    // -----------------------------------------------------------------
    let listUpdateTimer = null;

    function throttledUpdateList(aircraft) {
        if (listUpdateTimer) return;
        listUpdateTimer = setTimeout(() => {
            listUpdateTimer = null;
            updateAircraftList(aircraft);
        }, 500);
    }

    function updateAircraftList(aircraft) {
        aircraftCountBadge.textContent = aircraft.length;

        // Sort: emergencies first, then by callsign
        const sorted = [...aircraft].sort((a, b) => {
            if (a.em && !b.em) return -1;
            if (!a.em && b.em) return 1;
            return (a.cs || '').localeCompare(b.cs || '');
        });

        // Build HTML (reuse DOM when possible)
        const fragment = document.createDocumentFragment();

        for (const ac of sorted) {
            const div = document.createElement('div');
            div.className = 'aircraft-item' + (ac.em ? ' emergency' : '');
            div.dataset.id = ac.id;

            const altStr = ac.a >= 10000
                ? 'FL' + Math.round(ac.a / 100)
                : Math.round(ac.a) + 'ft';

            div.innerHTML = `
                <span class="callsign">${ac.cs}</span>
                <span class="alt">${altStr}</span>
                <span class="status-tag ${ac.st}">${ac.st}</span>
            `;

            div.addEventListener('mouseenter', () => showTooltipForAircraft(ac, div));
            div.addEventListener('mouseleave', hideTooltip);

            fragment.appendChild(div);
        }

        aircraftList.innerHTML = '';
        aircraftList.appendChild(fragment);
    }

    // -----------------------------------------------------------------
    // Tooltip
    // -----------------------------------------------------------------
    function showTooltipForAircraft(ac, element) {
        document.getElementById('tt-callsign').textContent = ac.cs;
        document.getElementById('tt-type').textContent = '';
        document.getElementById('tt-altitude').textContent =
            ac.a >= 10000 ? 'FL' + Math.round(ac.a / 100) : Math.round(ac.a) + ' ft';
        document.getElementById('tt-speed').textContent = Math.round(ac.s) + ' kt';
        document.getElementById('tt-heading').textContent = Math.round(ac.h) + '\u00B0';
        document.getElementById('tt-status').textContent = ac.st;

        tooltip.classList.remove('hidden');

        // Position near the element
        const rect = element.getBoundingClientRect();
        const containerRect = document.getElementById('radar-container').getBoundingClientRect();
        tooltip.style.left = (containerRect.right - 180) + 'px';
        tooltip.style.top = Math.min(rect.top, window.innerHeight - 120) + 'px';
    }

    function hideTooltip() {
        tooltip.classList.add('hidden');
    }

    // Radar canvas hover
    canvas.addEventListener('mousemove', (e) => {
        const acId = scene.getAircraftAtScreen(e.clientX, e.clientY);
        if (acId && lastAircraftArray) {
            const ac = lastAircraftArray.find(a => a.id === acId);
            if (ac) {
                document.getElementById('tt-callsign').textContent = ac.cs;
                document.getElementById('tt-type').textContent = '';
                document.getElementById('tt-altitude').textContent =
                    ac.a >= 10000 ? 'FL' + Math.round(ac.a / 100) : Math.round(ac.a) + ' ft';
                document.getElementById('tt-speed').textContent = Math.round(ac.s) + ' kt';
                document.getElementById('tt-heading').textContent = Math.round(ac.h) + '\u00B0';
                document.getElementById('tt-status').textContent = ac.st;

                tooltip.classList.remove('hidden');
                tooltip.style.left = (e.clientX + 15) + 'px';
                tooltip.style.top = (e.clientY - 10) + 'px';
                return;
            }
        }
        tooltip.classList.add('hidden');
    });

    // -----------------------------------------------------------------
    // Controls
    // -----------------------------------------------------------------
    btnStart.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/simulation/start', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'started' || data.status === 'already_running') {
                simStatus.textContent = 'RUNNING';
                simStatus.className = 'status-badge running';
                btnStart.disabled = true;
                btnStop.disabled = false;
            }
        } catch (err) {
            console.error('Failed to start simulation:', err);
        }
    });

    btnStop.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/simulation/stop', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'stopped' || data.status === 'already_stopped') {
                simStatus.textContent = 'STOPPED';
                simStatus.className = 'status-badge stopped';
                btnStart.disabled = false;
                btnStop.disabled = true;
            }
        } catch (err) {
            console.error('Failed to stop simulation:', err);
        }
    });

    altitudeFilter.addEventListener('input', () => {
        const val = parseInt(altitudeFilter.value);
        altitudeFilterValue.textContent = val.toLocaleString();
        scene.altitudeFilter = val;
    });

    showLabels.addEventListener('change', () => {
        scene.showLabels = showLabels.checked;
    });

    showTrails.addEventListener('change', () => {
        scene.showTrails = showTrails.checked;
    });

    btnResetCamera.addEventListener('click', () => {
        scene.resetCamera();
    });

    // -----------------------------------------------------------------
    // Check initial sim state
    // -----------------------------------------------------------------
    (async function checkInitialState() {
        try {
            const res = await fetch('/api/stats');
            if (res.ok) {
                const data = await res.json();
                if (data.running) {
                    simStatus.textContent = 'RUNNING';
                    simStatus.className = 'status-badge running';
                    btnStart.disabled = true;
                    btnStop.disabled = false;
                }
            }
        } catch (err) {
            // Server not ready yet
        }
    })();

    // -----------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------
    function pad(n) {
        return n < 10 ? '0' + n : '' + n;
    }
})();
