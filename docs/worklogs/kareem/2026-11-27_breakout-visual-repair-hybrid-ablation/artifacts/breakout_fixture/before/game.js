"use strict";

const CANVAS_WIDTH = 640;
const CANVAS_HEIGHT = 420;
const BRICK_ROWS = 4;
const BRICK_COLS = 8;
const BRICK_WIDTH = 66;
const BRICK_HEIGHT = 20;
const BRICK_GAP = 10;
const BRICK_OFFSET_TOP = 36;
const BRICK_OFFSET_LEFT = 22;
const BRICK_POINTS = 10;
const HIGHSCORE_KEY = "neon_breakout_highscore";
const ROW_COLORS = ["#f472b6", "#c084fc", "#38bdf8", "#34d399"];

function createBricks() {
  const bricks = [];
  for (let row = 0; row < BRICK_ROWS; row += 1) {
    for (let col = 0; col < BRICK_COLS; col += 1) {
      bricks.push({
        row,
        col,
        x: BRICK_OFFSET_LEFT + col * (BRICK_WIDTH + BRICK_GAP),
        y: BRICK_OFFSET_TOP + row * (BRICK_HEIGHT + BRICK_GAP),
        width: BRICK_WIDTH,
        height: BRICK_HEIGHT,
        color: ROW_COLORS[row % ROW_COLORS.length],
        alive: true,
      });
    }
  }
  return bricks;
}

function loadHighScore(storage) {
  return 0;
}

function saveHighScore(storage, value) {
  return false;
}

function createInitialState(storage) {
  return {
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
    score: 0,
    highScore: loadHighScore(storage),
    lives: 3,
    status: "playing", // "playing" | "paused" | "gameover" | "won"
    paddle: {
      width: 104,
      height: 14,
      x: (CANVAS_WIDTH - 104) / 2,
      y: CANVAS_HEIGHT - 30,
      speed: 7,
    },
    ball: {
      x: CANVAS_WIDTH / 2,
      y: CANVAS_HEIGHT - 48,
      r: 8,
      dx: 3.5,
      dy: -3.5,
    },
    bricks: createBricks(),
  };
}

function resetBallAndPaddle(state) {
  state.paddle.x = (state.width - state.paddle.width) / 2;
  state.ball.x = state.width / 2;
  state.ball.y = state.height - 48;
  state.ball.dx = 3.5;
  state.ball.dy = -3.5;
}

function resetGame(state) {
  resetBallAndPaddle(state);
  return state;
}

function togglePause(state) {
  state.status = "paused";
  return state.status;
}

function movePaddle(state, deltaX) {
  state.paddle.x = Math.max(
    0,
    Math.min(state.width - state.paddle.width, state.paddle.x + deltaX)
  );
}

function stepGame(state, storage) {
  if (state.status !== "playing") {
    return state;
  }

  const { ball, paddle } = state;
  ball.x += ball.dx;
  ball.y += ball.dy;

  // Wall collisions
  if (ball.x - ball.r < 0) {
    ball.x = ball.r;
    ball.dx = Math.abs(ball.dx);
  } else if (ball.x + ball.r > state.width) {
    ball.dx = Math.abs(ball.dx);
  }

  if (ball.y - ball.r < 0) {
    ball.y = ball.r;
    ball.dy = Math.abs(ball.dy);
  }

  // Paddle collision
  const hitPaddleX = ball.x + ball.r >= paddle.x && ball.x - ball.r <= paddle.x + paddle.width;
  const hitPaddleY =
    ball.dy > 0 &&
    ball.y + ball.r >= paddle.y &&
    ball.y - ball.r <= paddle.y + paddle.height;
  if (hitPaddleX && hitPaddleY) {
    const offset = (ball.x - (paddle.x + paddle.width / 2)) / (paddle.width / 2);
    ball.y = paddle.y - ball.r;
    ball.dx = Math.max(-5.5, Math.min(5.5, offset * 5));
    if (Math.abs(ball.dx) < 1.2) {
      ball.dx = ball.dx < 0 ? -1.5 : 1.5;
    }
    ball.dy = -Math.abs(ball.dy);
  }

  // Brick collisions
  for (const brick of state.bricks) {
    if (!brick.alive) {
      continue;
    }
    const overlapX = ball.x + ball.r >= brick.x && ball.x - ball.r <= brick.x + brick.width;
    const overlapY = ball.y + ball.r >= brick.y && ball.y - ball.r <= brick.y + brick.height;
    if (overlapX && overlapY) {
      brick.alive = false;
      ball.dy = -ball.dy;
      break;
    }
  }

  // Bottom miss
  if (ball.y - ball.r > state.height) {
    resetBallAndPaddle(state);
  }

  return state;
}

function renderGame(ctx, state) {
  ctx.fillStyle = "#060913";
  ctx.fillRect(0, 0, state.width, state.height);

  // Subtle grid lines
  ctx.strokeStyle = "rgba(56, 189, 248, 0.06)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= state.width; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, state.height);
    ctx.stroke();
  }

  // Bricks
  for (const brick of state.bricks) {
    if (!brick.alive) continue;
    ctx.fillStyle = brick.color;
    ctx.fillRect(brick.x, brick.y, brick.width, brick.height);
  }

  // Paddle
  ctx.fillStyle = "#38bdf8";
  ctx.fillRect(state.paddle.x, state.paddle.y, state.paddle.width, state.paddle.height);

  // Ball
  ctx.beginPath();
  ctx.arc(state.ball.x, state.ball.y, state.ball.r, 0, Math.PI * 2);
  ctx.fillStyle = "#f8fafc";
  ctx.fill();
}

function initBrowserApp() {
  const canvas = document.getElementById("gameCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const scoreEl = document.getElementById("score-val");
  const highEl = document.getElementById("highscore-val");
  const livesEl = document.getElementById("lives-val");
  const badgeEl = document.getElementById("status-badge");
  const overlayEl = document.getElementById("overlay");
  const overlayTitle = document.getElementById("overlay-title");
  const overlayMessage = document.getElementById("overlay-message");
  const pauseBtn = document.getElementById("pause-btn");
  const restartBtn = document.getElementById("restart-btn");
  const overlayRestartBtn = document.getElementById("overlay-restart-btn");

  const storage = typeof window !== "undefined" ? window.localStorage : null;
  const state = createInitialState(storage);
  const keys = { left: false, right: false };

  function syncHud() {
    scoreEl.textContent = String(state.score);
    highEl.textContent = String(state.highScore);
    livesEl.textContent = String(state.lives);
    badgeEl.textContent = state.status.toUpperCase();

    if (state.status === "playing") {
      overlayEl.classList.add("hidden");
    } else {
      overlayEl.classList.remove("hidden");
      if (state.status === "paused") {
        overlayTitle.textContent = "Paused";
        overlayMessage.textContent = "Press Space to resume or R to restart.";
      } else if (state.status === "gameover") {
        overlayTitle.textContent = "Game Over";
        overlayMessage.textContent = `Final Score: ${state.score} · Best: ${state.highScore}`;
      } else if (state.status === "won") {
        overlayTitle.textContent = "Victory!";
        overlayMessage.textContent = `All bricks cleared! Score: ${state.score}`;
      }
    }
  }

  window.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") keys.left = true;
    if (event.key === "ArrowRight") keys.right = true;
    if (event.code === "Space") {
      event.preventDefault();
      togglePause(state);
      syncHud();
    }
    if (event.key === "r" || event.key === "R") {
      resetGame(state);
      syncHud();
    }
  });

  window.addEventListener("keyup", (event) => {
    if (event.key === "ArrowLeft") keys.left = false;
    if (event.key === "ArrowRight") keys.right = false;
  });

  canvas.addEventListener("mousemove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * state.width;
    state.paddle.x = Math.max(0, Math.min(state.width - state.paddle.width, relX - state.paddle.width / 2));
  });

  pauseBtn.addEventListener("click", () => {
    togglePause(state);
    syncHud();
  });

  const handleRestart = () => {
    resetGame(state);
    syncHud();
  };
  restartBtn.addEventListener("click", handleRestart);
  overlayRestartBtn.addEventListener("click", handleRestart);

  function frame() {
    if (state.status === "playing") {
      if (keys.left) movePaddle(state, -state.paddle.speed);
      if (keys.right) movePaddle(state, state.paddle.speed);
      stepGame(state, storage);
    }
    renderGame(ctx, state);
    syncHud();
    window.requestAnimationFrame(frame);
  }

  renderGame(ctx, state);
  syncHud();
  window.requestAnimationFrame(frame);
}

if (typeof document !== "undefined") {
  initBrowserApp();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    BRICK_COLS,
    BRICK_POINTS,
    BRICK_ROWS,
    HIGHSCORE_KEY,
    createBricks,
    createInitialState,
    loadHighScore,
    movePaddle,
    resetBallAndPaddle,
    resetGame,
    saveHighScore,
    stepGame,
    togglePause,
  };
}
