<template><div><div class="page-head"><div><h1>上传学习素材</h1><p class="muted">拍照或选择图片，上传到 Aerial Study</p></div></div>
<div v-if="error" class="panel" style="color:#b33">{{error}}</div>
<div v-else class="panel"><p v-if="info">分类：{{ categoryName(info.token.categoryId) }} · 剩余 {{ info.token.maxUploads - info.token.usedCount }} 次</p><div class="row"><label class="grow">分类<select v-model="categoryId"><option v-for="x in info?.taxonomy?.materialCategories||[]" :key="x.id" :value="x.id">{{x.name}}</option></select></label><input type="file" accept="image/png,image/jpeg,image/webp" @change="pick"></div><div class="row" style="margin-top:12px"><button @click="upload" :disabled="!file||busy">{{ busy?'上传中…':'上传' }}</button></div><p v-if="message" class="muted">{{message}}</p></div></div></template>
<script setup>
import {ref,onMounted} from 'vue'; import {useRoute} from 'vue-router'; import {api} from '../api'
const route=useRoute(); const info=ref(null); const error=ref(''); const file=ref(null); const categoryId=ref(null); const busy=ref(false); const message=ref('')
function categoryName(id){return info.value?.taxonomy?.materialCategories?.find(x=>x.id===id)?.name||'未分类'}
function pick(e){file.value=e.target.files?.[0]||null}
async function upload(){ if(!file.value) return; busy.value=true; const fd=new FormData(); fd.append('raw_token',route.params.token); fd.append('file',file.value); if(categoryId.value) fd.append('categoryId',categoryId.value); try{ await api('/api/v1/mobile/uploads',{method:'POST',body:fd}); message.value='上传成功'; file.value=null; }catch(e){error.value=e.message}finally{busy.value=false} }
onMounted(async()=>{ try{ info.value=await api('/api/v1/mobile/upload-tokens/'+route.params.token); categoryId.value=info.value.token.categoryId }catch(e){error.value=e.message} })
</script>
