export function createGameState() {
    return {
        ship: { x: 0, z: 0 },
        prisms: Array.from({ length: 8 }).map((_, i) => ({
            id: i,
            x: Number((6 * Math.cos(i * Math.PI / 4)).toFixed(2)),
            z: Number((6 * Math.sin(i * Math.PI / 4)).toFixed(2)),
            active: true,
        })),
        score: 0,
        collected: 0,
        totalPrisms: 8,
        paused: false,
        won: false,
    };
}

export function collectNearbyPrisms(state) {
    state.prisms.forEach(p => {
        if (p.active && Math.hypot(state.ship.x - p.x, state.ship.z - p.z) <= 1.6) {
            p.active = false;
            state.collected += 1;
            state.score += 25;
            if (state.collected >= state.totalPrisms) {
                state.won = true;
            }
        }
    });
    return state;
}

export function stepShip(state, dx, dz) {
    if (state.paused || state.won) {
        return state;
    }
    state.ship.x = Math.max(-10, Math.min(10, state.ship.x + dx));
    state.ship.z = Math.max(-10, Math.min(10, state.ship.z + dz));
    collectNearbyPrisms(state);
    return state;
}

export function forceCollectOne(state) {
    const activePrism = state.prisms.find(p => p.active);
    if (activePrism) {
        state.ship.x = activePrism.x;
        state.ship.z = activePrism.z;
        activePrism.active = false;
        state.collected += 1;
        state.score += 25;
        if (state.collected >= state.totalPrisms) {
            state.won = true;
        }
    }
    return state;
}

export function forceWinAll(state) {
    state.prisms.forEach(p => p.active = false);
    state.collected = state.totalPrisms;
    state.score = state.totalPrisms * 25;
    state.won = true;
    return state;
}

export function setPaused(state, flag) {
    state.paused = Boolean(flag);
    return state;
}

export function resetGameState(state) {
    state.ship = { x: 0, z: 0 };
    state.prisms.forEach(p => p.active = true);
    state.score = 0;
    state.collected = 0;
    state.paused = false;
    state.won = false;
    return state;
}
