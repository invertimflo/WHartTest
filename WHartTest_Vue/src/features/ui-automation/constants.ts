/**
 * UI 自动化共享常量。
 *
 * 这些表原先分别维护在 StepDetailList.vue（页面步骤编辑器）与 CaseStepList.vue
 * （用例步骤编辑器）里，两份逐渐漂移：用例侧的「步骤数据覆盖」只认 8 种操作方法，
 * 用户想覆盖 press / goto / assert_url 等参数时根本没有入口。
 *
 * 现在统一为一份，且覆盖用的主参数键由参数定义派生（见 OPE_PRIMARY_PARAM），
 * 新增操作方法时只要在 OPE_PARAMS_MAP 里加一条，覆盖面板自动获得对应字段。
 */

/** 操作参数定义 */
export interface OpeParamDef {
  field: string
  label: string
  type: 'input' | 'number' | 'textarea' | 'file'
  placeholder: string
  required?: boolean
  min?: number
  max?: number
}

/** 单个「等待」步骤的时长上限（秒），与执行器 MAX_WAIT_SECONDS 一致 */
export const MAX_WAIT_SECONDS = 300

/** 操作方法与参数的映射 */
export const OPE_PARAMS_MAP: Record<string, OpeParamDef[]> = {
  // 元素操作
  fill: [{ field: 'text', label: '输入内容', type: 'input', placeholder: '请输入要填充的文本', required: true }],
  type: [{ field: 'text', label: '输入内容', type: 'input', placeholder: '请输入要键入的文本', required: true }],
  wait: [{ field: 'timeout', label: '等待时间(秒)', type: 'number', placeholder: '默认1', min: 0, max: MAX_WAIT_SECONDS }],
  screenshot: [{ field: 'name', label: '截图文件名', type: 'input', placeholder: '可选，留空自动生成' }],
  select_option: [{ field: 'value', label: '选项值', type: 'input', placeholder: '请输入要选择的选项值', required: true }],
  press: [{ field: 'key', label: '按键值', type: 'input', placeholder: '例如 Enter, Tab, Escape 等', required: true }],
  upload: [{ field: 'file_id', label: '上传文件', type: 'file', placeholder: '请选择要上传的文件', required: true }],
  goto: [{ field: 'url', label: '目标 URL', type: 'input', placeholder: '请输入完整的网页地址，例如 https://www.google.com', required: true }],
  switch_tab: [{ field: 'value', label: '页签索引或关键字', type: 'input', placeholder: '请输入页签索引(从0开始)或URL/标题关键字', required: true }],
  // 断言操作
  assert_text: [{ field: 'expected', label: '期望文本', type: 'input', placeholder: '请输入期望的文本内容', required: true }],
  assert_contain_text: [{ field: 'expected', label: '期望包含的文本', type: 'input', placeholder: '请输入期望被包含的文本', required: true }],
  assert_value: [{ field: 'expected', label: '期望值', type: 'input', placeholder: '请输入期望的值', required: true }],
  assert_count: [{ field: 'expected', label: '期望数量', type: 'number', placeholder: '请输入期望的元素数量', required: true, min: 0 }],
  assert_url: [{ field: 'expected', label: '期望 URL', type: 'input', placeholder: '例如 https://example.com/dashboard', required: true }],
  assert_title: [{ field: 'expected', label: '期望页面标题', type: 'input', placeholder: '例如 首页', required: true }],
}

/**
 * 每种操作方法的「主参数键」（用例步骤数据覆盖用）。
 *
 * 由 OPE_PARAMS_MAP 的首个参数定义派生 —— 若另立一张表，迟早与参数定义不一致。
 * 与后端 `ui_automation/step_overrides.py` 的 OPE_PRIMARY_PARAM 保持同源。
 */
export const OPE_PRIMARY_PARAM: Record<string, string> = Object.fromEntries(
  Object.entries(OPE_PARAMS_MAP)
    .map(([opeKey, defs]) => [opeKey, defs[0]?.field])
    .filter(([, field]) => !!field),
) as Record<string, string>

/** 需要按数字打开的覆盖输入框（其余按文本） */
export const OPE_NUMERIC_OVERRIDE = new Set(['wait', 'assert_count'])

/** 上传步骤依赖文件选择器，不做文本覆盖 */
export const OPE_OVERRIDE_EXCLUDED = new Set(['upload'])

/** 操作方法标签映射 */
export const OPE_KEY_LABELS: Record<string, string> = {
  click: '点击',
  dblclick: '双击',
  hover: '悬停',
  focus: '聚焦',
  fill: '填充',
  type: '输入',
  clear: '清空',
  press: '按键模拟',
  captcha_recognize: '智能识别验证码',
  select_option: '选择下拉',
  check: '勾选',
  uncheck: '取消勾选',
  upload: '上传文件',
  goto: '访问网页',
  reload: '刷新页面',
  go_back: '页面后退',
  go_forward: '页面前进',
  switch_tab: '切换页签',
  wait: '等待',
  wait_load: '等待页面加载',
  wait_network: '等待网络空闲',
  screenshot: '截图',
  assert_visible: '元素可见',
  assert_hidden: '元素隐藏',
  assert_enabled: '元素已启用',
  assert_disabled: '元素被禁用',
  assert_checked: '单/复选框被选中',
  assert_text: '文本等于',
  assert_contain_text: '文本包含',
  assert_value: '值等于',
  assert_count: '数量等于',
  assert_url: '页面URL等于',
  assert_title: '页面标题等于',
}

/**
 * 尚未实现运行时的步骤类型（自定义变量 3 / 条件判断 4 / Python代码 5）。
 *
 * 前端保留展示但禁用：这三类在录制器与执行器两端都没有执行逻辑，允许配置只会
 * 让用户以为「配了就能跑」。运行时实现单独立项。
 */
export const STEP_TYPE_UNSUPPORTED: readonly number[] = [3, 4, 5]

/** 是否为暂不支持的步骤类型 */
export const isStepTypeUnsupported = (stepType: number | string | undefined): boolean =>
  STEP_TYPE_UNSUPPORTED.includes(Number(stepType))
