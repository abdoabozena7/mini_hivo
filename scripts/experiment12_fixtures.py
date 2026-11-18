"""Public, disposable regression tasks; no solutions enter Worker workspaces."""

ARENA = '''<!doctype html>
<html><head><title>Grid Arena</title></head><body>
<canvas width="320" height="200"></canvas><p id="state" aria-live="polite"></p>
<button data-move="up">Up</button><button id="restart">Restart</button>
<script>
let state;
function render() { document.getElementById('state').textContent = state.status + ' ' + state.score; }
function restart() { state = {status:'playing', score:0, player:{row:0,col:0}}; render(); }
function move(direction) { if(state.status !== 'playing') return; if(direction === 'up') state.player.row += 1; state.score = state.player.row; render(); }
function forceCollision() { state.status='gameover'; render(); }
function forceWin() { state.status='won'; state.score=10; state.player.row=10; render(); }
document.addEventListener('keydown', function(event) {
  if(event.key === 'ArrowUp') move('up');
  // Extra restart key is intentionally not connected yet.
});
document.querySelector('[data-move="up"]').addEventListener('pointerdown', () => move('up'));
document.getElementById('restart').addEventListener('click', restart);
window.ARENA = {getState:()=>JSON.parse(JSON.stringify(state)), restart, start:restart, move, forceCollision, forceWin};
restart();
</script></body></html>
'''

TIMER = '''<!doctype html>
<html><head><title>Desk Countdown</title><style>#clock {font-size:48px}</style></head>
<body><h1>Desk Countdown</h1><p id="clock" aria-live="polite">02:00</p>
<button id="start">Start</button><button id="pause">Pause</button><button id="reset">Reset</button>
<script>
const duration=120;
let remaining=duration;
let interval=null;
function render() { document.getElementById('clock').textContent=String(Math.floor(remaining/60)).padStart(2,'0')+':'+String(remaining%60).padStart(2,'0'); }
function start() { if(interval!==null) return; interval=setInterval(()=>{remaining=Math.max(0,remaining-1);render();},1000); }
function pause() { /* Pause is not connected to the running interval yet. */ }
function reset() { clearInterval(interval); interval=null; remaining=duration; render(); }
document.getElementById('start').addEventListener('click',start);
document.getElementById('pause').addEventListener('click',pause);
document.getElementById('reset').addEventListener('click',reset);
render();
</script></body></html>
'''

PYTHON = '''def clamp_number(value, lower, upper):
    """Clamp a numeric value to inclusive bounds; inverted bounds are invalid."""
    if lower > upper:
        raise ValueError("inverted bounds")
    return max(lower, value)
'''

PYTHON_TEST = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from numbers_api import clamp_number

class ClampBehavior(unittest.TestCase):
    def test_above_upper(self): self.assertEqual(clamp_number(99, 0, 10), 10)
    def test_below_lower(self): self.assertEqual(clamp_number(-2, 0, 10), 0)
    def test_inside(self): self.assertEqual(clamp_number(2.5, 0, 10), 2.5)
    def test_boundary(self): self.assertEqual(clamp_number(10, 0, 10), 10)
    def test_inverted_bounds(self):
        with self.assertRaises(ValueError): clamp_number(4, 10, 0)

if __name__ == '__main__': unittest.main(verbosity=2)
'''

NODE = '''function uniqueValues(values) {
  // Return each primitive value once, preserving its first occurrence order.
  return [...values].sort();
}
module.exports = {uniqueValues};
'''

NODE_TEST = '''const assert=require('node:assert/strict');
const {uniqueValues}=require('../values.js');
assert.deepEqual(uniqueValues([3,1,3,2,1]), [3,1,2]);
assert.deepEqual(uniqueValues(['b','a','b']), ['b','a']);
assert.deepEqual(uniqueValues([]), []);
const original=[2,1,2]; uniqueValues(original); assert.deepEqual(original,[2,1,2]);
console.log('unique behavior tests: 4 passed');
'''

CASES = [
    {"case_id":"arena_arrow", "family":"browser_game", "source":"arena.html", "symbol":"move",
     "goal":"Fix the arena game's ArrowUp keyboard movement so the player moves up, while preserving existing touch controls.",
     "files":{"arena.html":ARENA.replace("if(event.key === 'ArrowUp') move('up');", "if(event.key === 'ArrowDown') move('up');")},
     "integration_target":"arena.html", "expected_interactions":["keyboard_movement","touch_control"]},
    {"case_id":"arena_q_restart", "family":"browser_game", "source":"arena.html", "symbol":"restart",
     "goal":"Allow the Q key to restart the arena game after game over or win, while preserving existing keyboard and touch controls.",
     "files":{"arena.html":ARENA}, "integration_target":"arena.html",
     "expected_interactions":["keyboard_movement","restart_resets_state","goal_win_state","touch_control"]},
    {"case_id":"timer_pause", "family":"browser_timer", "source":"timer.html", "symbol":"pause",
     "goal":"Fix Pause in the countdown timer so it freezes the visible time without resetting it, while preserving Start and Reset.",
     "files":{"timer.html":TIMER}, "integration_target":"timer.html",
     "expected_interactions":["timer_start_changes_visible_time","timer_pause_freezes_visible_time","timer_reset_restores_visible_time"]},
    {"case_id":"python_clamp", "family":"python_unit_behavior", "source":"numbers_api.py", "symbol":"clamp_number",
     "goal":"Fix clamp_number so values above upper clamp to upper, while preserving lower-bound clamping, values inside the bounds, and ValueError for inverted bounds.",
     "files":{"numbers_api.py":PYTHON,"tests/test_clamp.py":PYTHON_TEST},
     "test_target":"tests/test_clamp.py", "integration_target":"python tests/test_clamp.py", "expected_tests":5},
    {"case_id":"node_unique", "family":"node_unit_behavior", "source":"values.js", "symbol":"uniqueValues",
     "goal":"Fix uniqueValues so it removes duplicate primitive values while preserving first-occurrence order, the original input array, and the empty-array behavior.",
     "files":{"values.js":NODE,"tests/unique.test.js":NODE_TEST},
     "test_target":"tests/unique.test.js", "integration_target":"node tests/unique.test.js", "expected_tests":4},
]


def get_case(case_id):
    return next(c for c in CASES if c["case_id"] == case_id)
