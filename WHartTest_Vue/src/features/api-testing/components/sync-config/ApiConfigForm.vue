<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import type { ApiInterface, TestCase, TestStep } from '../../services/syncService'
import { syncApi } from '../../services/syncService'
import { useProjectStore } from '@/store/projectStore'

const projectStore = useProjectStore()

const props = defineProps<{
  visible: boolean
  loading: boolean
  isEditing: boolean
  fieldOptions: { label: string; value: string }[]
  currentConfig?: any
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'submit', data: any): void
}>()

interface FormModel {
  name: string
  description: string
  interface: number | undefined
  testcase: number | undefined
  step: number | undefined
  sync_fields: string[]
  sync_enabled: boolean
  sync_mode: 'manual' | 'auto'
  sync_trigger: {
    fields_to_watch: string[]
  }
}

const formModel = reactive<FormModel>({
  name: '',
  description: '',
  interface: undefined,
  testcase: undefined,
  step: undefined,
  sync_fields: [],
  sync_enabled: true,
  sync_mode: 'manual',
  sync_trigger: {
    fields_to_watch: []
  }
})

// 添加接口、用例和步骤的列表数据
const interfaces = ref<ApiInterface[]>([])
const testcases = ref<TestCase[]>([])
const teststeps = ref<TestStep[]>([])

// 添加加载状态
const loadingInterfaces = ref(false)
const loadingTestcases = ref(false)
const loadingTestSteps = ref(false)

// 添加一个标志位，用于避免重复请求
const isLoadingStepsFromConfig = ref(false);

// 获取接口列表
const fetchInterfaces = async () => {
  if (!projectStore.currentProject?.id) {
    Message.error('请先选择项目')
    return
  }

  try {
    loadingInterfaces.value = true
    const { data } = await syncApi.getInterfaces(projectStore.currentProject.id)
    interfaces.value = data.results
  } catch (error) {
    Message.error('获取接口列表失败')
    console.error(error)
  } finally {
    loadingInterfaces.value = false
  }
}

// 获取用例列表
const fetchTestCases = async () => {
  if (!projectStore.currentProject?.id) {
    Message.error('请先选择项目')
    return
  }

  try {
    loadingTestcases.value = true
    const { data } = await syncApi.getTestCases(projectStore.currentProject.id)
    testcases.value = data.results
  } catch (error) {
    Message.error('获取用例列表失败')
    console.error(error)
  } finally {
    loadingTestcases.value = false
  }
}

// 获取步骤列表
const fetchTestSteps = async () => {
  if (!formModel.testcase) {
    teststeps.value = []
    return
  }
  
  try {
    loadingTestSteps.value = true
    const { data } = await syncApi.getTestSteps(formModel.testcase)
    // 适配新的API返回格式
    teststeps.value = data.steps?.map(step => ({
      id: step.id,
      name: step.name,
      order: step.order,
      interface_info: step.interface_info
    })) || []
  } catch (error) {
    console.error('获取步骤列表失败:', error)
    Message.error('获取步骤列表失败')
    teststeps.value = []
  } finally {
    loadingTestSteps.value = false
  }
}

// 监听用例选择变化
watch(() => formModel.testcase, (newTestcaseId) => {
  // 如果是从配置加载步骤，则不重复请求
  if (isLoadingStepsFromConfig.value) {
    return;
  }
  
  formModel.step = undefined;
  teststeps.value = [];
  if (newTestcaseId) {
    fetchTestSteps();
  }
})

// 监听currentConfig变化，用于编辑时回显数据
watch(() => props.currentConfig, async (newConfig) => {
  if (props.isEditing && newConfig) {
    // 设置标志位，避免重复请求
    isLoadingStepsFromConfig.value = true;
    
    try {
      // 先加载接口和用例列表
      await Promise.all([fetchInterfaces(), fetchTestCases()]);
      
      // 填充表单数据
      formModel.name = newConfig.name || '';
      formModel.description = newConfig.description || '';
      
      // 设置接口、用例和步骤ID
      // 确保使用正确的ID
      formModel.interface = newConfig.interface;
      formModel.testcase = newConfig.testcase;
      
      // 检查接口是否在列表中
      const interfaceExists = interfaces.value && interfaces.value.some(item => item.id === formModel.interface);
      if (!interfaceExists && newConfig.interface_info) {
        console.warn('警告：当前接口ID不在接口列表中，添加接口到列表');
        interfaces.value = interfaces.value || [];
        interfaces.value.push({
          id: newConfig.interface,
          name: newConfig.interface_info.name,
          method: newConfig.interface_info.method,
          url: newConfig.interface_info.url
        });
      }
      
      // 检查用例是否在列表中
      const testcaseExists = testcases.value && testcases.value.some(item => item.id === formModel.testcase);
      if (!testcaseExists && newConfig.testcase_info) {
        console.warn('警告：当前用例ID不在用例列表中，添加用例到列表');
        testcases.value = testcases.value || [];
        testcases.value.push({
          id: newConfig.testcase,
          name: newConfig.testcase_info.name
        });
      }
      
      // 先获取步骤列表，然后再设置步骤值
      if (formModel.testcase) {
        await fetchTestSteps();
        
        // 在步骤列表加载完成后设置步骤值
        formModel.step = newConfig.step;
        
        // 检查步骤是否在列表中
        const stepExists = teststeps.value && teststeps.value.some(step => step.id === newConfig.step);
        if (!stepExists && newConfig.step_info) {
          console.warn('警告：当前步骤ID不在步骤列表中，添加步骤到列表');
          
          // 如果步骤不在列表中，添加它到列表中
          teststeps.value = teststeps.value || [];
          teststeps.value.push({
            id: newConfig.step,
            name: newConfig.step_info.name,
            order: newConfig.step_info.order
          });
        }
      }
      
      // 设置同步字段
      formModel.sync_fields = Array.isArray(newConfig.sync_fields) ? [...newConfig.sync_fields] : [];
      formModel.sync_enabled = newConfig.sync_enabled === true;
      formModel.sync_mode = newConfig.sync_mode || 'manual';
      
      // 设置同步触发器
      if (newConfig.sync_mode === 'auto' && newConfig.sync_trigger && newConfig.sync_trigger.fields_to_watch) {
        formModel.sync_trigger.fields_to_watch = [...newConfig.sync_trigger.fields_to_watch];
      } else {
        formModel.sync_trigger.fields_to_watch = [];
      }

    } catch (error) {
    } finally {
      // 重置标志位
      isLoadingStepsFromConfig.value = false;
    }
  }
}, { immediate: true })

// 监听visible变化，当弹窗打开时获取数据
watch(() => props.visible, (newVisible) => {
  if (newVisible && !props.isEditing) {
    // 只有在新建模式下才初始化加载数据
    // 编辑模式下的数据加载由currentConfig的watch处理
    fetchInterfaces();
    fetchTestCases();
  }
}, { immediate: true })

const handleSubmit = () => {
  const { interface: interfaceId, testcase: testcaseId, step: stepId } = formModel
  if (!interfaceId || !testcaseId || !stepId) {
    Message.error('请填写必填项')
    return
  }

  emit('submit', {
    name: formModel.name,
    description: formModel.description,
    interface: interfaceId,
    testcase: testcaseId,
    step: stepId,
    sync_fields: formModel.sync_fields,
    sync_enabled: formModel.sync_enabled,
    sync_mode: formModel.sync_mode,
    sync_trigger: formModel.sync_mode === 'auto' ? formModel.sync_trigger : undefined
  })
}

const handleClose = () => {
  // 先发送关闭事件
  emit('update:visible', false)
  
  // 重置标志位
  isLoadingStepsFromConfig.value = false;
  
  // 延迟重置表单数据，确保弹窗已关闭
  setTimeout(() => {
    // 重置表单数据
    formModel.name = '';
    formModel.description = '';
    formModel.interface = undefined;
    formModel.testcase = undefined;
    formModel.step = undefined;
    formModel.sync_fields = [];
    formModel.sync_enabled = true;
    formModel.sync_mode = 'manual';
    formModel.sync_trigger.fields_to_watch = [];
    
    // 清空步骤列表
    teststeps.value = [];
  }, 200);
}

defineExpose({
  formModel
})
</script>

<template>
  <a-modal
    :visible="visible"
    :title="isEditing ? '编辑同步配置' : '新建同步配置'"
    :width="780"
    class="custom-card"
    @ok="handleSubmit"
    @cancel="handleClose"
    @close="handleClose"
  >
    <a-form :model="formModel" layout="vertical">
      <a-form-item field="name" label="配置名称" required>
        <a-input
          v-model="formModel.name"
          placeholder="请输入配置名称"
          allow-clear
        />
      </a-form-item>

      <a-form-item field="description" label="配置描述">
        <a-textarea
          v-model="formModel.description"
          placeholder="请输入配置描述"
          allow-clear
        />
      </a-form-item>

      <a-form-item field="interface" label="选择接口" required>
        <a-select
          v-model="formModel.interface"
          placeholder="请选择接口"
          :loading="loadingInterfaces"
        >
          <a-option
            v-for="item in interfaces"
            :key="item.id"
            :value="item.id"
            :label="item.name"
          />
        </a-select>
      </a-form-item>

      <a-form-item field="testcase" label="选择用例" required>
        <a-select
          v-model="formModel.testcase"
          placeholder="请选择用例"
          :loading="loadingTestcases"
        >
          <a-option
            v-for="item in testcases"
            :key="item.id"
            :value="item.id"
            :label="item.name"
          />
        </a-select>
      </a-form-item>

      <a-form-item field="step" label="选择步骤" required>
        <a-select
          v-model="formModel.step"
          placeholder="请选择步骤"
          :loading="loadingTestSteps"
        >
          <a-option
            v-for="item in teststeps"
            :key="item.id"
            :value="item.id"
            :label="`${item.name} (步骤${item.order})`"
          />
        </a-select>
      </a-form-item>

      <a-form-item field="sync_fields" label="同步字段" required>
        <a-select
          v-model="formModel.sync_fields"
          placeholder="请选择同步字段"
          multiple
        >
          <a-option
            v-for="option in fieldOptions"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          />
        </a-select>
      </a-form-item>

      <a-form-item field="sync_mode" label="同步模式" required>
        <a-radio-group v-model="formModel.sync_mode">
          <a-radio value="manual">手动同步</a-radio>
          <a-radio value="auto">自动同步</a-radio>
        </a-radio-group>
      </a-form-item>

      <a-form-item
        v-if="formModel.sync_mode === 'auto'"
        field="sync_trigger.fields_to_watch"
        label="监视字段"
      >
        <a-select
          v-model="formModel.sync_trigger.fields_to_watch"
          placeholder="请选择需要监视的字段"
          multiple
        >
          <a-option
            v-for="option in fieldOptions"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          />
        </a-select>
      </a-form-item>

      <div class="flex justify-between items-center mt-4 pt-4 border-t border-gray-700">
        <a-checkbox v-model="formModel.sync_enabled">
          <template #default>
            <span class="text-gray-300">启用同步</span>
          </template>
        </a-checkbox>
      </div>
    </a-form>
  </a-modal>
</template>

<style scoped>
@reference "tailwindcss";
:deep(.arco-form-item-label-col) {
  @apply text-gray-300;
}

:deep(.arco-radio) {
  @apply text-gray-300;
}

:deep(.arco-checkbox) {
  @apply text-gray-300;
}

:deep(.arco-input-wrapper) {
  @apply bg-gray-700 border-gray-600;
}

:deep(.arco-input-wrapper:hover) {
  @apply border-blue-500;
}

:deep(.arco-input) {
  @apply text-gray-300;
}

:deep(.arco-textarea) {
  @apply bg-gray-700 border-gray-600 text-gray-300;
}

:deep(.arco-textarea:hover) {
  @apply border-blue-500;
}

:deep(.arco-select-view) {
  @apply bg-gray-700 border-gray-600 text-gray-300;
}

:deep(.arco-select-view:hover) {
  @apply border-blue-500;
}

:deep(.arco-modal) {
  @apply bg-gray-800;
}

:deep(.arco-modal-header) {
  @apply bg-gray-800 border-gray-700 pb-4;
}

:deep(.arco-modal-title) {
  @apply text-gray-200 text-lg font-medium;
}

:deep(.arco-modal-footer) {
  @apply bg-gray-800 border-gray-700 mt-6;
}

:deep(.arco-modal-body) {
  @apply p-4;
}
</style> 