"use strict";

const fs = require("fs");
const path = require("path");

const targetDir = path.resolve(process.argv[2] || ".");
const htmlPath = path.join(targetDir, "index.html");
const cssPath = path.join(targetDir, "style.css");
const jsPath = path.join(targetDir, "game.js");

const results = [];
function check(id, category, fn) {
  try {
    const detail = fn();
    results.push({ id, category, passed: true, detail: detail || "ok" });
  } catch (err) {
    results.push({ id, category, passed: false, detail: err && err.message ? err.message : String(err) });
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function makeMemoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial).map(([k, v]) => [String(k), String(v)]));
  return {
    getItem(k) { return map.has(String(k)) ? map.get(String(k)) : null; },
    setItem(k, v) { map.set(String(k), String(v)); },
    removeItem(k) { map.delete(String(k)); },
    _dump() { return Object.fromEntries(map.entries()); },
  };
}

function extractCssBlock(css, selectorRegex) {
  const m = css.match(selectorRegex);
  return m ? m[1] : "";
}

const html = fs.readFileSync(htmlPath, "utf8");
const css = fs.readFileSync(cssPath, "utf8");

// 1. Visual CSS: HUD does not overlap playfield via position: absolute / fixed
check("css_hud_no_overlap", "visual_layout", () => {
  const hudBlock = extractCssBlock(css, /\.hud\s*\{([^}]*)\}/m);
  assert(hudBlock.length > 0, "Missing .hud CSS rule");
  assert(!/position\s*:\s*(absolute|fixed)/i.test(hudBlock), `.hud still uses absolute/fixed positioning: ${hudBlock.trim()}`);
  return "HUD sits in normal layout flow above the canvas";
});

// 2. Visual CSS: Hidden overlay does not block pointer events
check("css_overlay_hidden_nonblocking", "visual_layout", () => {
  const hiddenBlock = extractCssBlock(css, /\.overlay\.hidden\s*\{([^}]*)\}/m);
  assert(hiddenBlock.length > 0, "Missing .overlay.hidden CSS rule");
  const blocksClicks = !(/display\s*:\s*none/i.test(hiddenBlock) || /pointer-events\s*:\s*none/i.test(hiddenBlock));
  assert(!blocksClicks, `.overlay.hidden lacks display:none or pointer-events:none: ${hiddenBlock.trim()}`);
  return "Hidden overlay properly disables visibility/pointer interception";
});

// Load game.js fresh
delete require.cache[require.resolve(jsPath)];
let game;
try {
  game = require(jsPath);
} catch (err) {
  console.log(JSON.stringify({
    target_dir: targetDir,
    load_error: err.message,
    passed: 0,
    total: 10,
    checks: results,
  }, null, 2));
  process.exit(1);
}

// 3. Right wall collision clamps x and reverses dx leftward
check("physics_right_wall_bounce", "gameplay_physics", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  s.ball.x = s.width - s.ball.r - 1;
  s.ball.y = 200;
  s.ball.dx = 4;
  s.ball.dy = 0;
  game.stepGame(s, storage);
  assert(s.ball.dx < 0, `Expected negative ball.dx after right-wall hit, got ${s.ball.dx}`);
  assert(s.ball.x <= s.width - s.ball.r, `Expected ball.x <= ${s.width - s.ball.r}, got ${s.ball.x}`);
  return `ball.x=${s.ball.x}, ball.dx=${s.ball.dx}`;
});

// 4. Brick collision awards +10 score and marks brick dead
check("brick_hit_increments_score", "gameplay_scoring", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  const b = s.bricks[0];
  s.ball.x = b.x + b.width / 2;
  s.ball.y = b.y + b.height + s.ball.r - 1;
  s.ball.dx = 0;
  s.ball.dy = -3;
  game.stepGame(s, storage);
  assert(b.alive === false, "Target brick was not marked dead");
  assert(s.score === game.BRICK_POINTS, `Expected score=${game.BRICK_POINTS}, got ${s.score}`);
  return `score=${s.score}, brick.alive=${b.alive}`;
});

// 5. Clearing final remaining brick sets status='won'
check("clear_last_brick_triggers_win", "gameplay_state", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  for (let i = 1; i < s.bricks.length; i += 1) s.bricks[i].alive = false;
  const last = s.bricks[0];
  s.ball.x = last.x + last.width / 2;
  s.ball.y = last.y + last.height + s.ball.r - 1;
  s.ball.dx = 0;
  s.ball.dy = -3;
  game.stepGame(s, storage);
  assert(last.alive === false, "Last brick not destroyed");
  assert(s.status === "won", `Expected status='won', got '${s.status}'`);
  return `status=${s.status}, score=${s.score}`;
});

// 6. Bottom miss decrements lives and resets ball while lives > 0
check("bottom_miss_decrements_lives", "gameplay_lives", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  s.ball.x = 10;
  s.ball.y = s.height + s.ball.r + 2;
  s.ball.dx = 0;
  s.ball.dy = 4;
  game.stepGame(s, storage);
  assert(s.lives === 2, `Expected lives=2 after 1 miss, got ${s.lives}`);
  assert(s.status === "playing", `Expected status='playing' with 2 lives left, got '${s.status}'`);
  assert(s.ball.y < s.height, `Expected ball reset inside playfield, got y=${s.ball.y}`);
  return `lives=${s.lives}, status=${s.status}`;
});

// 7. Losing final life transitions to status='gameover' and freezes simulation
check("zero_lives_triggers_gameover", "gameplay_state", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  s.lives = 1;
  s.ball.x = 10;
  s.ball.y = s.height + s.ball.r + 2;
  s.ball.dx = 0;
  s.ball.dy = 4;
  game.stepGame(s, storage);
  assert(s.lives === 0, `Expected lives=0, got ${s.lives}`);
  assert(s.status === "gameover", `Expected status='gameover', got '${s.status}'`);
  const frozenX = s.ball.x;
  const frozenY = s.ball.y;
  game.stepGame(s, storage);
  assert(s.ball.x === frozenX && s.ball.y === frozenY, "Ball continued moving after gameover");
  return `lives=${s.lives}, status=${s.status}`;
});

// 8. Pause toggles cleanly between playing <-> paused and ignores gameover/won
check("pause_toggle_and_terminal_guard", "gameplay_controls", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  game.togglePause(s);
  assert(s.status === "paused", `Expected 'paused', got '${s.status}'`);
  game.togglePause(s);
  assert(s.status === "playing", `Expected unpause back to 'playing', got '${s.status}'`);
  s.status = "gameover";
  game.togglePause(s);
  assert(s.status === "gameover", `Pause corrupted terminal 'gameover' state to '${s.status}'`);
  s.status = "won";
  game.togglePause(s);
  assert(s.status === "won", `Pause corrupted terminal 'won' state to '${s.status}'`);
  return "playing <-> paused toggle works; gameover/won protected";
});

// 9. Restart fully resets score, lives, status, bricks while preserving highScore
check("restart_full_state_reset_preserves_highscore", "gameplay_controls", () => {
  const storage = makeMemoryStorage();
  const s = game.createInitialState(storage);
  s.score = 120;
  s.highScore = 120;
  s.lives = 0;
  s.status = "gameover";
  s.bricks[0].alive = false;
  s.bricks[1].alive = false;
  game.resetGame(s);
  const aliveCount = s.bricks.filter((b) => b.alive).length;
  const expectedBricks = game.BRICK_ROWS * game.BRICK_COLS;
  assert(s.score === 0, `Expected score=0 after reset, got ${s.score}`);
  assert(s.lives === 3, `Expected lives=3 after reset, got ${s.lives}`);
  assert(s.status === "playing", `Expected status='playing' after reset, got '${s.status}'`);
  assert(aliveCount === expectedBricks, `Expected ${expectedBricks} alive bricks after reset, got ${aliveCount}`);
  assert(s.highScore === 120, `Expected highScore=120 preserved after reset, got ${s.highScore}`);
  return `score=0, lives=3, status=playing, bricks=${aliveCount}/${expectedBricks}, highScore=${s.highScore}`;
});

// 10. High score persists to and loads from storage under HIGHSCORE_KEY
check("highscore_persistence", "persistence", () => {
  const storage = makeMemoryStorage({ [game.HIGHSCORE_KEY]: "70" });
  const s = game.createInitialState(storage);
  assert(s.highScore === 70, `Expected loaded highScore=70, got ${s.highScore}`);
  // Score 80 via breaking bricks
  s.score = 70;
  const b = s.bricks[0];
  s.ball.x = b.x + b.width / 2;
  s.ball.y = b.y + b.height + s.ball.r - 1;
  s.ball.dx = 0;
  s.ball.dy = -3;
  game.stepGame(s, storage);
  assert(s.highScore === 80, `Expected updated highScore=80, got ${s.highScore}`);
  assert(storage.getItem(game.HIGHSCORE_KEY) === "80", `Expected persisted '${game.HIGHSCORE_KEY}'='80', got ${storage.getItem(game.HIGHSCORE_KEY)}`);
  // Ensure fresh session loads 80
  const s2 = game.createInitialState(storage);
  assert(s2.highScore === 80, `Fresh session failed to reload highScore=80, got ${s2.highScore}`);
  return `loaded=70 -> updated=80 -> persisted='${storage.getItem(game.HIGHSCORE_KEY)}'`;
});

const passed = results.filter((r) => r.passed).length;
const output = {
  target_dir: targetDir,
  html_bytes: Buffer.byteLength(html, "utf8"),
  css_bytes: Buffer.byteLength(css, "utf8"),
  passed,
  total: results.length,
  all_passed: passed === results.length,
  checks: results,
};
console.log(JSON.stringify(output, null, 2));
process.exit(output.all_passed ? 0 : 1);
