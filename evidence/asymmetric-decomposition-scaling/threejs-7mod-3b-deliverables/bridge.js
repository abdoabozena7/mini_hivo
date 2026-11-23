import {stepShip, forceCollectOne, forceWinAll, setPaused, resetGameState} from './game_state.js';

export function createGameBridge(state, onUpdate) {
    function snap() {
        return {
            player: {x: state.ship.x, y: 0.6, z: state.ship.z},
            position: {x: state.ship.x, z: state.ship.z},
            score: state.score,
            collected: state.collected,
            totalPrisms: state.totalPrisms,
            paused: Boolean(state.paused),
            won: Boolean(state.won),
            status: state.won ? 'won' : (state.paused ? 'paused' : 'playing')
        };
    }

    return {
        getState: () => snap(),
        move: (dir) => {
            const dx = dir === 'left' ? -0.8 : (dir === 'right' ? 0.8 : 0);
            const dz = dir === 'up' ? 0.8 : (dir === 'down' ? -0.8 : 0);
            stepShip(state, dx, dz);
            onUpdate();
            return snap();
        },
        forceCollect: () => {
            forceCollectOne(state);
            onUpdate();
            return snap();
        },
        forceWin: () => {
            forceWinAll(state);
            onUpdate();
            return snap();
        },
        togglePause: () => {
            setPaused(state, !state.paused);
            onUpdate();
            return snap();
        },
        restart: () => {
            resetGameState(state);
            onUpdate();
            return snap();
        }
    };
}
