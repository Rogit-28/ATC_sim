/**
 * ATC Simulator — WebSocket Client
 *
 * Connects to the server WebSocket, receives msgpack binary frames,
 * and dispatches decoded data to registered callbacks.
 */

/* global msgpack */

class ATCWebSocket {
    constructor(url) {
        this.url = url || `ws://${window.location.host}/ws`;
        this.ws = null;
        this.connected = false;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 10000;
        this.currentDelay = this.reconnectDelay;
        this.reconnectTimer = null;
        this.frameCount = 0;
        this.lastFrameTime = 0;
        this.fps = 0;

        // Callbacks
        this._onFrame = null;
        this._onConnect = null;
        this._onDisconnect = null;
    }

    /**
     * Register callback for each decoded frame.
     * @param {function} callback - Called with decoded frame object
     */
    onFrame(callback) {
        this._onFrame = callback;
    }

    onConnect(callback) {
        this._onConnect = callback;
    }

    onDisconnect(callback) {
        this._onDisconnect = callback;
    }

    /**
     * Open WebSocket connection with auto-reconnect.
     */
    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            return;
        }

        try {
            this.ws = new WebSocket(this.url);
            this.ws.binaryType = 'arraybuffer';

            this.ws.onopen = () => {
                console.log('[WS] Connected to', this.url);
                this.connected = true;
                this.currentDelay = this.reconnectDelay;
                if (this._onConnect) this._onConnect();
            };

            this.ws.onmessage = (event) => {
                this._handleMessage(event);
            };

            this.ws.onclose = (event) => {
                console.log('[WS] Disconnected:', event.code, event.reason);
                this.connected = false;
                if (this._onDisconnect) this._onDisconnect();
                this._scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.warn('[WS] Error:', error);
            };
        } catch (err) {
            console.error('[WS] Failed to connect:', err);
            this._scheduleReconnect();
        }
    }

    disconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.onclose = null; // Prevent reconnect
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    _handleMessage(event) {
        try {
            // Decode msgpack binary
            const data = event.data;
            const decoded = msgpack.decode(new Uint8Array(data));

            // FPS tracking
            this.frameCount++;
            const now = performance.now();
            if (now - this.lastFrameTime > 1000) {
                this.fps = this.frameCount;
                this.frameCount = 0;
                this.lastFrameTime = now;
            }

            if (this._onFrame) {
                this._onFrame(decoded);
            }
        } catch (err) {
            console.error('[WS] Failed to decode frame:', err);
        }
    }

    _scheduleReconnect() {
        if (this.reconnectTimer) return;

        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            console.log(`[WS] Reconnecting in ${this.currentDelay}ms...`);
            this.connect();

            // Exponential backoff
            this.currentDelay = Math.min(this.currentDelay * 1.5, this.maxReconnectDelay);
        }, this.currentDelay);
    }
}
