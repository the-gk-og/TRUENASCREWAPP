/* ShowWise camera scanner: getUserMedia + jsQR (QR codes) + Quagga2 (1D barcodes).
 * Shared by the equipment page and the unit check-out page.
 * Needs jsQR and Quagga loaded first (both optional: whichever is present is used).
 *
 *   const sc = SWScanner.create({
 *     container: el,                 // element the <video> is inserted into
 *     onCode(code) {},               // a decoded code
 *     onState(live, text) {},        // camera status changes
 *     isOpen() { return true; },     // false → camera is released right after the permission prompt
 *     continuous: false,             // true: keep scanning after a hit (same code ignored for repeatMs)
 *     repeatMs: 2500,
 *   });
 *   sc.start(); sc.stop(); sc.pause(true|false); sc.scanning
 */
(function () {
    'use strict';
    const READERS = ['code_128_reader', 'ean_reader', 'ean_8_reader', 'code_39_reader',
                     'upc_reader', 'upc_e_reader', 'codabar_reader'];

    function create(opts) {
        const o = Object.assign({ continuous: false, repeatMs: 2500, isOpen: () => true,
                                  onState: () => {}, onError: () => {} }, opts);
        let stream = null, video = null, canvas = null, ctx = null, raf = 0;
        let quaggaBusy = false, lastTick = 0, frameN = 0, paused = false;
        let lastCode = '', lastCodeAt = 0;
        const api = { scanning: false };

        api.start = async function () {
            if (api.scanning) return;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                o.onState(false, 'Camera not available here — type the code instead');
                o.onError('Camera needs a secure (https) connection');
                return;
            }
            o.onState(false, 'Starting camera…');
            try {
                try {
                    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
                } catch (e) {
                    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
                }
            } catch (err) {
                o.onState(false, 'Camera unavailable — type the code instead');
                o.onError('Camera unavailable: ' + (err && err.message ? err.message : err));
                return;
            }
            // The UI may have been closed while the permission prompt was showing
            if (!o.isOpen()) { stream.getTracks().forEach(t => t.stop()); stream = null; return; }

            api.scanning = true; paused = false;
            video = document.createElement('video');
            video.setAttribute('playsinline', ''); video.setAttribute('autoplay', ''); video.muted = true;
            video.srcObject = stream;
            o.container.insertBefore(video, o.container.firstChild);
            try { await video.play(); } catch (e) {}
            canvas = document.createElement('canvas');
            ctx = canvas.getContext('2d', { willReadFrequently: true });
            o.onState(true, 'Scanning — point at a barcode or QR code');
            raf = requestAnimationFrame(tick);
        };

        function tick(ts) {
            if (!api.scanning) return;
            raf = requestAnimationFrame(tick);
            if (paused || ts - lastTick < 130 || !video || video.readyState < 2 || !video.videoWidth) return;
            lastTick = ts;

            const scale = Math.min(1, 960 / video.videoWidth);
            const w = Math.round(video.videoWidth * scale), h = Math.round(video.videoHeight * scale);
            if (canvas.width !== w) { canvas.width = w; canvas.height = h; }
            ctx.drawImage(video, 0, 0, w, h);

            if (typeof jsQR === 'function') {
                try {
                    const img = ctx.getImageData(0, 0, w, h);
                    const qr = jsQR(img.data, w, h, { inversionAttempts: 'dontInvert' });
                    if (qr && qr.data) { hit(qr.data); return; }
                } catch (e) {}
            }
            if (typeof Quagga !== 'undefined' && !quaggaBusy && (++frameN % 2 === 0)) {
                quaggaBusy = true;
                try {
                    Quagga.decodeSingle({
                        src: canvas.toDataURL('image/jpeg', 0.8), numOfWorkers: 0, locate: true,
                        decoder: { readers: READERS }
                    }, res => {
                        quaggaBusy = false;
                        if (api.scanning && !paused && res && res.codeResult && res.codeResult.code) hit(res.codeResult.code);
                    });
                } catch (e) { quaggaBusy = false; }
            }
        }

        function hit(code) {
            if (!api.scanning || paused) return;
            const now = Date.now();
            if (o.continuous && code === lastCode && now - lastCodeAt < o.repeatMs) { lastCodeAt = now; return; }   // still in view
            lastCode = code; lastCodeAt = now;
            try { navigator.vibrate && navigator.vibrate([40, 20, 60]); } catch (e) {}
            if (!o.continuous) api.stop();
            o.onCode(code);
        }

        api.pause = function (on) {
            paused = !!on;
            if (!on) lastCodeAt = Date.now();      // don't instantly re-read the code still in view
        };

        api.stop = function () {
            api.scanning = false; paused = false;
            cancelAnimationFrame(raf);
            if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
            if (video) { video.srcObject = null; video.remove(); video = null; }
            canvas = ctx = null;
            o.onState(false, 'Camera off');
        };

        return api;
    }

    window.SWScanner = { create };
})();
