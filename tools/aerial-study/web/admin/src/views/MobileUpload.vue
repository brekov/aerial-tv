<template>
<div class="mobile-upload"><div class="brandline"><span class="brand-mark">A</span>Aerial Study</div><h1>上传学习素材</h1><p class="muted">拍照或选择图片，上传到 NAS 学习素材库</p>
<div v-if="error" class="notice" style="color:#b91c1c">{{error}}</div>
<template v-else>
<div class="upload-box" @click="$refs.file.click()"><div class="plus">＋</div><b>{{file?file.name:'拍照 / 选择图片'}}</b><p>支持 PNG、JPEG、WebP</p></div><input ref="file" type="file" accept="image/png,image/jpeg,image/webp" style="display:none" @change="pick">
<label class="field" style="margin-top:16px">素材分类<select v-model="categoryId"><option :value="null">未分类</option><option v-for="x in info?.taxonomy?.materialCategories||[]" :key="x.id" :value="x.id">{{x.name}}</option></select></label>
<button class="btn" style="width:100%;height:48px;margin-top:20px" :disabled="!file||busy" @click="upload">{{busy?'上传中…':'选择图片并上传'}}</button>
<p class="muted" style="text-align:center;font-size:11px;margin-top:12px">上传后可在电脑端继续整理和生成题目</p>
<div v-if="message" class="notice" style="margin-top:14px;background:#eefaf2;border-color:#ccebd8;color:#277444">✓ {{message}}</div>
</template></div>
</template>
<script setup>
import{ref,onMounted}from'vue';import{useRoute}from'vue-router';import{api}from'../api'
const route=useRoute(),info=ref(null),error=ref(''),file=ref(null),categoryId=ref(null),busy=ref(false),message=ref('')
function pick(e){file.value=e.target.files?.[0]||null}
async function upload(){if(!file.value)return;busy.value=true;const fd=new FormData();fd.append('raw_token',route.params.token);fd.append('file',file.value);if(categoryId.value)fd.append('categoryId',categoryId.value);try{await api('/api/v1/mobile/uploads',{method:'POST',body:fd});message.value='上传成功，可以继续选择图片';file.value=null}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(async()=>{try{info.value=await api('/api/v1/mobile/upload-tokens/'+route.params.token);categoryId.value=info.value.token.categoryId}catch(e){error.value=e.message}})
</script>
<style scoped>.mobile-upload{padding:22px 20px;max-width:430px;margin:0 auto}.brandline{display:flex;align-items:center;gap:9px;font-weight:700;margin-bottom:28px}.brandline .brand-mark{width:32px;height:32px;border-radius:10px;background:#2563eb;color:#fff;display:grid;place-items:center}.mobile-upload h1{font-size:25px;margin:0 0 6px}.upload-box{height:210px;border:1.5px dashed #b9ceef;border-radius:18px;background:#f8fbff;display:grid;place-items:center;text-align:center;color:#627a9e}.plus{width:52px;height:52px;border-radius:50%;background:#e7f0ff;color:#2563eb;display:grid;place-items:center;font-size:29px;margin:0 auto 9px}.upload-box b{color:#244e89;font-size:14px}.upload-box p{font-size:12px;color:#8ca0ba;margin:4px 0 0}</style>
