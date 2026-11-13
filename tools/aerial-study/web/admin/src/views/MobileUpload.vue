<template>
<div class="mobile-upload"><div class="brandline"><span class="brand-mark">A</span>Aerial Study</div><h1>上传学习素材</h1><p class="muted">拍照或一次选择多张图片，上传到 NAS 学习素材库</p>
<div v-if="error" class="notice" style="color:#b91c1c">{{error}}</div>
<template v-else>
<div class="upload-box" @click="choose"><div class="plus">＋</div><b>{{files.length ? `已选 ${files.length} 张图片` : '拍照 / 选择图片'}}</b><p>支持 PNG、JPEG、WebP，可多选</p></div>
<input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" multiple style="display:none" @change="pick">
<div v-if="files.length" class="picked">
  <div v-for="(item, index) in files" :key="item.url" class="picked-row">
    <img :src="item.url" :alt="item.file.name">
    <div class="picked-name"><b>{{item.file.name}}</b><span>{{size(item.file.size)}}</span></div>
    <span v-if="states[index]==='ok'" class="pill green">已上传</span>
    <span v-else-if="states[index]==='fail'" class="pill red">失败</span>
    <button v-else class="close" :disabled="busy" @click="remove(index)">×</button>
  </div>
</div>
<label class="field" style="margin-top:16px">素材分类<select v-model="categoryId"><option :value="null">未分类</option><option v-for="x in info?.taxonomy?.materialCategories||[]" :key="x.id" :value="x.id">{{x.name}}</option></select></label>
<button class="btn" style="width:100%;height:48px;margin-top:20px" :disabled="!files.length||busy" @click="upload">{{busy?'上传中…':`上传 ${files.length} 张图片`}}</button>
<p class="muted" style="text-align:center;font-size:11px;margin-top:12px">上传后可在电脑端继续整理和生成题目</p>
<div v-if="message" class="notice" :style="messageClass" style="margin-top:14px">{{message}}</div>
</template></div>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
const route = useRoute()
const info = ref(null), error = ref(''), fileInput = ref(null), files = ref([]), states = ref([]), categoryId = ref(null), busy = ref(false), message = ref('')
const MAX_FILES = 20, MAX_BYTES = 10 * 1024 * 1024
function choose() { fileInput.value?.click() }
function size(bytes) { return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function pick(e) {
  const selected = Array.from(e.target.files || []).filter(f => f.type.startsWith('image/'))
  const merged = [...files.value.map(x => x.file), ...selected].slice(0, MAX_FILES)
  const tooBig = merged.find(f => f.size > MAX_BYTES)
  if (tooBig) { error.value = `${tooBig.name} 超过 10MB`; e.target.value = ''; return }
  files.value.forEach(x => URL.revokeObjectURL(x.url))
  files.value = merged.map(file => ({ file, url: URL.createObjectURL(file) }))
  states.value = files.value.map(() => '')
  message.value = ''
  e.target.value = ''
}
function remove(index) {
  URL.revokeObjectURL(files.value[index].url)
  files.value.splice(index, 1)
  states.value.splice(index, 1)
}
async function upload() {
  if (!files.value.length || busy.value) return
  busy.value = true; message.value = ''
  let ok = 0, failed = 0
  for (let i = 0; i < files.value.length; i++) {
    if (states.value[i] === 'ok') { ok++; continue }
    const fd = new FormData()
    fd.append('raw_token', route.params.token)
    fd.append('file', files.value[i].file)
    if (categoryId.value) fd.append('categoryId', categoryId.value)
    try {
      await api('/api/v1/mobile/uploads', { method: 'POST', body: fd })
      states.value[i] = 'ok'; ok++
    } catch (e) {
      states.value[i] = 'fail'; failed++
      message.value = e.message
    }
  }
  busy.value = false
  const result = `成功 ${ok} 张${failed ? `，失败 ${failed} 张` : ''}`
  message.value = result
  if (ok) {
    // Keep failed files for a retry; clear uploaded previews.
    const remaining = files.value.filter((_, i) => states.value[i] !== 'ok')
    files.value.forEach((item, i) => { if (states.value[i] === 'ok') URL.revokeObjectURL(item.url) })
    files.value = remaining
    states.value = remaining.map(() => '')
  }
}
const messageClass = { background: '#eefaf2', borderColor: '#ccebd8', color: '#277444' }
onMounted(async () => {
  try {
    info.value = await api('/api/v1/mobile/upload-tokens/' + route.params.token)
    categoryId.value = info.value.token.categoryId
  } catch (e) { error.value = e.message }
})
onBeforeUnmount(() => files.value.forEach(x => URL.revokeObjectURL(x.url)))
</script>
<style scoped>.mobile-upload{padding:22px 20px;max-width:430px;margin:0 auto}.brandline{display:flex;align-items:center;gap:9px;font-weight:700;margin-bottom:28px}.brandline .brand-mark{width:32px;height:32px;border-radius:10px;background:#2563eb;color:#fff;display:grid;place-items:center}.mobile-upload h1{font-size:25px;margin:0 0 6px}.upload-box{height:180px;border:1.5px dashed #b9ceef;border-radius:18px;background:#f8fbff;display:grid;place-items:center;text-align:center;color:#627a9e}.plus{width:52px;height:52px;border-radius:50%;background:#e7f0ff;color:#2563eb;display:grid;place-items:center;font-size:29px;margin:0 auto 9px}.upload-box b{color:#244e89;font-size:14px}.upload-box p{font-size:12px;color:#8ca0ba;margin:4px 0 0}.picked{margin-top:14px;display:flex;flex-direction:column;gap:8px}.picked-row{display:flex;align-items:center;gap:9px;background:#fff;border:1px solid #e6ecf5;border-radius:10px;padding:7px}.picked-row img{width:42px;height:36px;object-fit:contain;border-radius:6px;background:#f7f9fc}.picked-name{flex:1;min-width:0}.picked-name b{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.picked-name span{font-size:10px;color:#8a98aa}.picked .close{background:#f1f5fa;border-radius:7px;width:28px;height:28px;font-size:17px;color:#5b6b7e}</style>
