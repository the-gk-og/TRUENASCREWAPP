/* admin-poster.js - QR code + printable invite poster (moved unchanged from the old admin page).
 * Needs: qrcodejs, a #qrModal with #qrCodeImage/#qrCodeText, and a hidden <canvas id="posterCanvas">.
 * showModal / showAlert come from base.html. */
let currentInviteCode = '';
let currentSignupUrl = '';
let currentInviteExpiry = null;
let qrCodeInstance = null;

// ==================== QR CODE ====================
function generateQRCode(url, containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    qrCodeInstance = null;
    qrCodeInstance = new QRCode(container, {
        text: url,
        width: 220,
        height: 220,
        colorDark: '#1f2937',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
    });
}

function showQRCode() {
    if (!currentInviteCode) return;
    document.getElementById('qrCodeText').textContent = currentInviteCode;
    generateQRCode(currentSignupUrl, 'qrCodeImage');
    showModal('qrModal');
}

function openQRForExisting(code, url, expiresAt) {
    currentInviteCode = code;
    currentSignupUrl = url;
    currentInviteExpiry = expiresAt || null;
    document.getElementById('qrCodeText').textContent = code;
    generateQRCode(url, 'qrCodeImage');
    showModal('qrModal');
}

function downloadQR() {
    setTimeout(() => {
        const canvas = document.querySelector('#qrCodeImage canvas');
        if (!canvas) { showAlert('QR code not ready yet', 'error'); return; }
        const link = document.createElement('a');
        link.download = `showwise-invite-${currentInviteCode}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();
    }, 200);
}

// ==================== PDF POSTER ====================
function downloadPoster() {
    if (!currentInviteCode) return;
    downloadPosterForCode(currentInviteCode, currentSignupUrl, currentInviteExpiry);
}

function downloadPosterForCode(code, signupUrl, expiresAt) {
    currentInviteCode = code;
    currentSignupUrl = signupUrl;
    currentInviteExpiry = expiresAt || null;

    const tempDiv = document.createElement('div');
    tempDiv.style.cssText = 'position:absolute;left:-9999px;top:-9999px;';
    document.body.appendChild(tempDiv);

    new QRCode(tempDiv, {
        text: signupUrl,
        width: 600,
        height: 600,
        colorDark: '#1f2937',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
    });

    setTimeout(() => {
        const qrCanvas = tempDiv.querySelector('canvas');
        buildPosterPDF(code, signupUrl, qrCanvas, expiresAt);
        document.body.removeChild(tempDiv);
    }, 500);
}

function buildPosterPDF(code, signupUrl, qrCanvas, expiresAt) {
    const canvas = document.getElementById('posterCanvas');
    const W = 2480, H = 3508;
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    const S = W / 794;
    const sc = n => n * S;

    const grad = ctx.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, '#6366f1');
    grad.addColorStop(1, '#a855f7');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    const cardX = sc(20), cardY = sc(20), cardW = W - sc(40), cardH = H - sc(40);
    ctx.fillStyle = '#ffffff';
    roundRect(ctx, cardX, cardY, cardW, cardH, sc(24));
    ctx.fill();

    ctx.fillStyle = '#1f2937';
    ctx.textAlign = 'center';
    ctx.font = `bold ${sc(58)}px system-ui, Arial, sans-serif`;
    ctx.fillText('Join ShowWise', W / 2, cardY + sc(100));

    ctx.font = `${sc(26)}px system-ui, Arial, sans-serif`;
    ctx.fillStyle = '#6b7280';
    ctx.fillText('Scan the QR code or use the invite code below', W / 2, cardY + sc(148));

    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = sc(2);
    ctx.beginPath();
    ctx.moveTo(cardX + sc(60), cardY + sc(170));
    ctx.lineTo(cardX + cardW - sc(60), cardY + sc(170));
    ctx.stroke();

    if (qrCanvas) {
        const qrSize = sc(280);
        const qrX = (W - qrSize) / 2;
        const qrY = cardY + sc(195);

        ctx.fillStyle = '#f9fafb';
        roundRect(ctx, qrX - sc(20), qrY - sc(20), qrSize + sc(40), qrSize + sc(40), sc(16));
        ctx.fill();
        ctx.strokeStyle = '#e5e7eb';
        ctx.lineWidth = sc(2);
        roundRect(ctx, qrX - sc(20), qrY - sc(20), qrSize + sc(40), qrSize + sc(40), sc(16));
        ctx.stroke();
        ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize);
    }

    ctx.font = `bold ${sc(22)}px system-ui, Arial, sans-serif`;
    ctx.fillStyle = '#6366f1';
    ctx.textAlign = 'center';
    ctx.fillText('📱 Scan to join', W / 2, cardY + sc(195) + sc(280) + sc(55));

    ctx.font = `${sc(16)}px monospace`;
    ctx.fillStyle = '#9ca3af';
    ctx.textAlign = 'center';
    const shortUrl = signupUrl.replace('https://', '').replace('http://', '');
    ctx.fillText(shortUrl, W / 2, cardY + sc(195) + sc(280) + sc(85));

    const midY = cardY + sc(195) + sc(280) + sc(120);
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = sc(1.5);
    ctx.setLineDash([sc(6), sc(4)]);
    ctx.beginPath();
    ctx.moveTo(cardX + sc(60), midY);
    ctx.lineTo(cardX + cardW - sc(60), midY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.font = `${sc(18)}px system-ui, Arial, sans-serif`;
    ctx.fillStyle = '#9ca3af';
    ctx.fillText("Can't scan? Enter the code manually", W / 2, midY + sc(30));

    const codeBoxY = midY + sc(50);
    const codeBoxH = sc(90);
    const codeBoxX = cardX + sc(60);
    const codeBoxW = cardW - sc(120);

    const codeGrad = ctx.createLinearGradient(codeBoxX, 0, codeBoxX + codeBoxW, 0);
    codeGrad.addColorStop(0, '#ede9fe');
    codeGrad.addColorStop(1, '#fce7f3');
    ctx.fillStyle = codeGrad;
    roundRect(ctx, codeBoxX, codeBoxY, codeBoxW, codeBoxH, sc(12));
    ctx.fill();

    ctx.strokeStyle = '#a855f7';
    ctx.lineWidth = sc(2);
    roundRect(ctx, codeBoxX, codeBoxY, codeBoxW, codeBoxH, sc(12));
    ctx.stroke();

    ctx.font = `bold ${sc(46)}px monospace`;
    ctx.fillStyle = '#4c1d95';
    ctx.textAlign = 'center';
    ctx.fillText(code, W / 2, codeBoxY + sc(57));

    ctx.font = `${sc(15)}px system-ui, Arial, sans-serif`;
    ctx.fillStyle = '#7c3aed';
    ctx.fillText('INVITE CODE — Use at signup', W / 2, codeBoxY + sc(79));

    if (expiresAt) {
        const expDate = new Date(expiresAt);
        const expStr = expDate.toLocaleDateString('en-AU', {
            day: 'numeric', month: 'long', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
        ctx.font = `${sc(13)}px system-ui, Arial, sans-serif`;
        ctx.fillStyle = '#d1d5db';
        ctx.textAlign = 'center';
        ctx.fillText(`This invite expires ${expStr}`, W / 2, codeBoxY + codeBoxH + sc(28));
    }

    const footerY = cardY + cardH - sc(30);
    ctx.font = `${sc(15)}px system-ui, Arial, sans-serif`;
    ctx.fillStyle = '#9ca3af';
    ctx.textAlign = 'center';
    ctx.fillText('ShowWise — Production Crew Management', W / 2, footerY);

    canvas.toBlob(blob => {
        const link = document.createElement('a');
        link.download = `showwise-invite-poster-${code}.png`;
        link.href = URL.createObjectURL(blob);
        link.click();
    }, 'image/png');

    showAlert('Poster downloaded!', 'success');
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

