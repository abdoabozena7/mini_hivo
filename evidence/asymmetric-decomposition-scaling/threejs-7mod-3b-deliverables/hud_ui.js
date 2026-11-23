import {stepShip} from './game_state.js';

const scoreEl = document.getElementById('score-val');
const prismsEl = document.getElementById('prisms-val');
const statusEl = document.getElementById('status-badge');
const hudPauseBtn = document.getElementById('btn-pause');

export function updateHud(state) {
    if (scoreEl) scoreEl.textContent = 'SCORE: ' + state.score;
    if (prismsEl) prismsEl.textContent = 'PRISMS: ' + state.collected + ' / ' + state.totalPrisms;
    if (statusEl) statusEl.textContent = state.won ? 'VICTORY' : (state.paused ? 'PAUSED' : 'PLAYING');
    if (hudPauseBtn) hudPauseBtn.textContent = state.paused ? 'Resume' : 'Pause';
}

const ctrlPauseBtn = document.getElementById('btn-pause');
const ctrlRestartBtn = document.getElementById('btn-restart');

export function bindControls(state, bridge, onUpdate) {
    if (ctrlPauseBtn) ctrlPauseBtn.addEventListener('click', () => bridge.togglePause());
    if (ctrlRestartBtn) ctrlRestartBtn.addEventListener('click', () => bridge.restart());
    window.addEventListener('keydown', (e) => {
        let dx = 0, dz = 0;
        switch (e.key) {
            case 'ArrowLeft': case 'a': dx = -0.8; break;
            case 'ArrowRight': case 'd': dx = 0.8; break;
            case 'ArrowUp': case 'w': dz = -0.8; break;
            case 'ArrowDown': case 's': dz = 0; break;
        }
        if (dx !== 0 || dz !== 0) {
            stepShip(state, dx, dz);
            onUpdate();
        }
    });
}
