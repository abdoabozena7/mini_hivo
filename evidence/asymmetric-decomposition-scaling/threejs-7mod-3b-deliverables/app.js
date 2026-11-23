import {createGameState} from './game_state.js';
import {createArenaEnv} from './arena_env.js';
import {createEntities, syncEntities} from './entities3d.js';
import {createGameBridge} from './bridge.js';
import {updateHud, bindControls} from './hud_ui.js';

let state = createGameState();
let env = createArenaEnv(document.getElementById('canvas-mount') || document.body);
let entities = createEntities(env.scene);

function onUpdate() {
    updateHud(state);
    syncEntities(entities, state, performance.now() / 1000);
    env.renderer.render(env.scene, env.camera);
}

function animate(ts) {
    syncEntities(entities, state, ts / 1000);
    env.renderer.render(env.scene, env.camera);
    requestAnimationFrame(animate);
}

window.AGENT_GAME = createGameBridge(state, onUpdate);
bindControls(state, window.AGENT_GAME, onUpdate);

onUpdate();
requestAnimationFrame(animate);
