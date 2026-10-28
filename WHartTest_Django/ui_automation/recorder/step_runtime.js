/**
 * 录制器步骤运行时 —— 纯函数集合（不依赖 playwright，可直接单测）。
 *
 * 从 recorder_server.js 抽出的原因：这些换算/比较规则与平台执行器
 * (WHartTest_Actuator/executor.py) 必须逐条一致，散落在 2500 行的进程脚本里
 * 既无法单测，也反复出现「同一个语义两处实现漂移」的事故（等待单位就是）。
 *
 * 约定：本文件的每个函数都不得访问全局 state、不得引入 Node 内置模块之外的依赖。
 */

// 单个等待步骤的上限（毫秒）。与执行器 MAX_WAIT_SECONDS 对应，防脏数据挂死用例。
const MAX_WAIT_MS = 300000;

/**
 * 等待时长（秒 → 毫秒）。
 *
 * 平台口径是「秒」（前端标注「等待时间(秒)」、执行器 _parse_wait_timeout 亦按秒）。
 * 历史数据里可能存在毫秒值，仅当数值 >= 1000 时才判定为毫秒直接返回 —— 1 秒以内
 * 不可能被当作毫秒录入，而 60 秒以内的合法秒数（旧实现以 60 为界）不该被误判。
 *
 * @param {*} value 秒数（字符串/数字）
 * @param {number} fallbackMs 无法解析时的兜底毫秒数
 * @returns {number} 毫秒
 */
function parseWaitMs(value, fallbackMs = 1000) {
  if (value === null || value === undefined || value === '') return fallbackMs;
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return fallbackMs;
  const ms = n >= 1000 ? n : n * 1000;
  return Math.min(Math.round(ms), MAX_WAIT_MS);
}

/**
 * 元素下标收窄（0 基，与执行器 locator.nth(index) 一致）。
 *
 * 注意空值判断必须放在最前：JS 中 Number(null) === 0、Number('') === 0，
 * 否则「未填下标」会被悄悄收窄成 nth(0)，破坏 strict 冲突检测与多元素匹配。
 *
 * @param {object} loc Playwright locator
 * @param {*} index 下标；null/undefined/'' 表示不收窄
 * @returns {object} 收窄后的 locator（非法值原样返回）
 */
function applyLocatorIndex(loc, index) {
  if (index === null || index === undefined || index === '') return loc;
  const n = Number(index);
  if (!Number.isInteger(n) || n < 0) return loc;
  return loc.nth(n);
}

/**
 * 拆分 iframe 链式定位表达式。
 *
 * 执行器支持 ">>" 与 ">>>"（含无空格写法），录制器此前只认带空格的 ' >> '，
 * 手工录入 'a>>b' 会被当成单个选择器而失败。统一按「两个及以上连续 >」切分。
 *
 * @param {*} value 链式表达式
 * @returns {string[]} 逐层选择器
 */
function splitIframeChain(value) {
  return String(value || '')
    .split(/\s*>{2,}\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 文本归一化：折叠连续空白（等价 Playwright to_have_text 的空白归一化）。 */
function normalizeText(text) {
  return String(text === null || text === undefined ? '' : text)
    .replace(/\s+/g, ' ')
    .trim();
}

/** 文本严格相等（归一化后比较）。 */
function textEquals(actual, expected) {
  return normalizeText(actual) === normalizeText(expected);
}

/** 文本包含（归一化后比较）。 */
function containsText(actual, expected) {
  const needle = normalizeText(expected);
  if (!needle) return true;
  return normalizeText(actual).includes(needle);
}

/** URL 比较前的归一化：去尾部斜杠，scheme/host 小写（query/hash 保留）。 */
function normalizeUrl(url) {
  const text = String(url || '').trim();
  if (!text) return '';
  const trimmed = text.replace(/\/+$/, '');
  const sep = trimmed.indexOf('://');
  if (sep === -1) return trimmed;
  const scheme = trimmed.slice(0, sep).toLowerCase();
  const rest = trimmed.slice(sep + 3);
  const slash = rest.indexOf('/');
  if (slash === -1) return `${scheme}://${rest.toLowerCase()}`;
  return `${scheme}://${rest.slice(0, slash).toLowerCase()}${rest.slice(slash)}`;
}

/** URL 严格相等（归一化后比较）。 */
function urlEquals(actual, expected) {
  return normalizeUrl(actual) === normalizeUrl(expected);
}

module.exports = {
  MAX_WAIT_MS,
  parseWaitMs,
  applyLocatorIndex,
  splitIframeChain,
  normalizeText,
  textEquals,
  containsText,
  normalizeUrl,
  urlEquals,
};
