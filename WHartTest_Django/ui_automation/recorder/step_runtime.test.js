/**
 * step_runtime 纯函数单测（node --test recorder/step_runtime.test.js）。
 *
 * 重点是等待单位：录制器曾把「等待 20 秒」按 20 毫秒执行，是本轮要修的 BUG。
 */
const test = require('node:test');
const assert = require('node:assert');

const {
  MAX_WAIT_MS,
  parseWaitMs,
  applyLocatorIndex,
  splitIframeChain,
  normalizeText,
  textEquals,
  containsText,
  urlEquals,
} = require('./step_runtime');

test('parseWaitMs: 秒按 1000 换算（BUG 回归锚点：20 秒必须是 20000 毫秒）', () => {
  assert.strictEqual(parseWaitMs(20), 20000);
  assert.strictEqual(parseWaitMs('20'), 20000);
  assert.strictEqual(parseWaitMs('2.5'), 2500);
  assert.strictEqual(parseWaitMs(0), 0);
});

test('parseWaitMs: >=1000 视为历史毫秒数据，原样返回', () => {
  assert.strictEqual(parseWaitMs(1000), 1000);
  assert.strictEqual(parseWaitMs(3000), 3000);
});

test('parseWaitMs: 空值/非法值走兜底', () => {
  assert.strictEqual(parseWaitMs(''), 1000);
  assert.strictEqual(parseWaitMs(null), 1000);
  assert.strictEqual(parseWaitMs(undefined), 1000);
  assert.strictEqual(parseWaitMs('abc'), 1000);
  assert.strictEqual(parseWaitMs(-5), 1000);
  assert.strictEqual(parseWaitMs('', 0), 0);
});

test('parseWaitMs: 上限 300 秒，防脏数据挂死用例', () => {
  assert.strictEqual(parseWaitMs(999), MAX_WAIT_MS); // 999 秒 → 超上限
  assert.strictEqual(parseWaitMs(999999), MAX_WAIT_MS);
});

/** 假 locator：只记录 nth 调用 */
function fakeLocator() {
  const calls = [];
  const loc = {
    calls,
    nth(n) {
      calls.push(n);
      return { narrowed: n, calls };
    },
  };
  return loc;
}

test('applyLocatorIndex: 空值不收窄（Number(null)===0 陷阱回归）', () => {
  const loc = fakeLocator();
  assert.strictEqual(applyLocatorIndex(loc, null), loc);
  assert.strictEqual(applyLocatorIndex(loc, undefined), loc);
  assert.strictEqual(applyLocatorIndex(loc, ''), loc);
  assert.deepStrictEqual(loc.calls, []);
});

test('applyLocatorIndex: 0 基，0 表示第一个元素', () => {
  const loc = fakeLocator();
  assert.deepStrictEqual(applyLocatorIndex(loc, 0), { narrowed: 0, calls: loc.calls });
  assert.deepStrictEqual(applyLocatorIndex(loc, 2), { narrowed: 2, calls: loc.calls });
  assert.deepStrictEqual(applyLocatorIndex(loc, '1'), { narrowed: 1, calls: loc.calls });
  assert.deepStrictEqual(loc.calls, [0, 2, 1]);
});

test('applyLocatorIndex: 负数/非法值不收窄', () => {
  const loc = fakeLocator();
  assert.strictEqual(applyLocatorIndex(loc, -1), loc);
  assert.strictEqual(applyLocatorIndex(loc, 'a'), loc);
  assert.deepStrictEqual(loc.calls, []);
});

test('splitIframeChain: 三种写法都能切开', () => {
  assert.deepStrictEqual(splitIframeChain('a >> b'), ['a', 'b']);
  assert.deepStrictEqual(splitIframeChain('a>>b'), ['a', 'b']);
  assert.deepStrictEqual(splitIframeChain('a >>> b'), ['a', 'b']);
  assert.deepStrictEqual(splitIframeChain('a >>> b >> c'), ['a', 'b', 'c']);
  assert.deepStrictEqual(splitIframeChain(''), []);
});

test('normalizeText / textEquals / containsText', () => {
  assert.strictEqual(normalizeText('  a\n b '), 'a b');
  assert.strictEqual(textEquals(' 欢迎  回来 ', '欢迎 回来'), true);
  assert.strictEqual(textEquals('欢迎回来', '欢迎'), false); // 严格相等，不是包含
  assert.strictEqual(containsText('欢迎回来', '欢迎'), true);
  assert.strictEqual(containsText('欢迎回来', ''), true);
});

test('urlEquals: 忽略尾部斜杠与 host 大小写', () => {
  assert.strictEqual(urlEquals('https://Example.com/a/', 'https://example.com/a'), true);
  assert.strictEqual(urlEquals('https://example.com/a', 'https://example.com/b'), false);
});
