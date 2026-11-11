<template>
<div>
  <header class="topbar"><div class="crumb">内容 / <b>素材库</b></div><div class="search">⌕ <span>搜索文件名、分类…</span></div><div class="top-actions"><button class="btn ghost" @click="scanOpen=true">目录扫描</button><button class="btn" @click="showQr">手机扫码上传</button><div class="avatar">AS</div></div></header>
  <div class="content">
    <div class="page-title"><div><h1>素材库</h1><p>按分类整理图片素材，支持手机上传和 NAS 目录扫描。</p></div><div class="quick-stats"><div class="stat"><span>全部素材</span><b>{{ materials.length }}</b></div><div class="stat"><span>当前筛选</span><b>{{ filtered.length }}</b></div><div class="stat"><span>未分类</span><b>{{ materials.filter(m=>!m.category?.id).length }}</b></div></div></div>
    <div class="notice">💡 <span><b>手机上传已开启。</b> 用手机扫描二维码，直接上传到 NAS 素材库；目录扫描不会重复导入相同图片。</span></div>
    <div class="panel" style="padding:12px;margin-bottom:14px"><div class="row">
      <label class="field">分类<select v-model="categoryId" @change="load"><option :value="null">全部</option><option v-for="c in tax.materialCategories" :key="c.id" :value="c.id">{{c.name}}</option></select></label>
      <label class="field">年龄<select v-model="ageGroupId" @change="load"><option :value="null">全部</option><option v-for="a in tax.ageGroups" :key="a.id" :value="a.id">{{a.name}}</option></select></label>
      <label class="field">学科<select v-model="subjectId" @change="load"><option :value="null">全部</option><option v-for="s in tax.subjects" :key="s.id" :value="s.id">{{s.name}}</option></select></label>
      <label class="field">来源<select v-model="source" @change="load"><option value="">全部</option><option value="phone">手机上传</option><option value="scan">目录扫描</option><option value="upload">网页上传</option></select></label>
      <button class="btn ghost" @click="load">刷新</button>
    </div></div>
    <div v-if="loading" class="gallery"><div v-for="i in 8" :key="i" class="skeleton" style="height:220px"></div></div>
    <div v-else-if="!filtered.length" class="panel empty"><b>暂无素材</b>用手机上传，或扫描 NAS 目录。</div>
    <div v-else class="gallery">
      <article v-for="m in filtered" :key="m.sha256" class="mat-card">
        <div class="mat-img" @click="preview=m"><img :src="m.url" :alt="m.title"></div>
        <div class="mat-title">{{ m.title }}</div>
        <div class="mat-meta"><span class="pill blue">{{ m.category?.name || '未分类' }}</span><span class="pill">{{ m.ageGroup?.name || '未分类' }}</span><span class="pill">{{ sourceText(m.source) }}</span></div>
        <div style="display:flex;gap:4px;margin-top:8px"><button class="link" @click="edit=m;editForm={title:m.title,categoryId:m.category?.id||null,ageGroupId:m.ageGroup?.id||null,subjectId:m.subject?.id||null}">编辑分类</button><button class="link" @click="preview=m">查看</button><button class="link danger" @click="removeMaterial(m)">删除</button></div>
      </article>
    </div>
  </div>
  <div v-if="preview" class="modal-backdrop" @click.self="preview=null"><div class="modal" style="max-width:760px"><div class="drawer-head" style="padding:0 0 12px"><h2>{{preview.title}}</h2><button class="close" @click="preview=null">×</button></div><div class="preview-img" style="height:380px"><img :src="preview.url"></div><div class="mat-meta"><span class="pill blue">{{preview.category?.name||'未分类'}}</span><span class="pill">{{preview.ageGroup?.name||'未分类'}}</span><span class="pill">{{sourceText(preview.source)}}</span></div></div></div>
  <div v-if="edit" class="modal-backdrop" @click.self="edit=null"><div class="modal"><h2>编辑素材</h2><p>{{edit.title}}</p><div class="form-grid"><label class="field full">标题<input v-model="editForm.title"></label><label class="field">分类<select v-model="editForm.categoryId"><option :value="null">未分类</option><option v-for="c in tax.materialCategories" :key="c.id" :value="c.id">{{c.name}}</option></select></label><label class="field">年龄<select v-model="editForm.ageGroupId"><option :value="null">未分类</option><option v-for="a in tax.ageGroups" :key="a.id" :value="a.id">{{a.name}}</option></select></label><label class="field">学科<select v-model="editForm.subjectId"><option :value="null">未分类</option><option v-for="s in tax.subjects" :key="s.id" :value="s.id">{{s.name}}</option></select></label></div><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px"><button class="btn ghost" @click="edit=null">取消</button><button class="btn" @click="saveMaterial">保存</button></div></div></div>
  <div v-if="qrOpen" class="modal-backdrop" @click.self="qrOpen=false"><div class="modal" style="text-align:center"><h2>手机上传学习素材</h2><p>用手机扫码，把图片上传到 NAS 学习素材库</p><img v-if="qrUrl" :src="qrUrl" style="width:230px;height:230px"><div v-else class="skeleton" style="width:230px;height:230px;margin:auto"></div><div style="display:flex;gap:8px;justify-content:center;margin-top:14px"><button class="btn ghost" @click="qrOpen=false">关闭</button><button class="btn" @click="makeQr">刷新二维码</button></div></div></div>
  <div v-if="scanOpen" class="modal-backdrop" @click.self="scanOpen=false"><div class="modal"><h2>目录扫描</h2><p>输入 NAS 中配置的扫描目录，递归导入图片。</p><div class="form-grid"><label class="field full">目录路径<input v-model="scanForm.root" placeholder="/data/inbox"></label><label class="field">分类<select v-model="scanForm.categoryId"><option :value="null">未分类</option><option v-for="c in tax.materialCategories" :key="c.id" :value="c.id">{{c.name}}</option></select></label><label class="field">递归<select v-model="scanForm.recursive"><option :value="true">是</option><option :value="false">否</option></select></label></div><pre v-if="scanResult" style="background:#f7f9fc;padding:10px;border-radius:8px;font-size:12px;max-height:180px;overflow:auto">{{ JSON.stringify(scanResult,null,2) }}</pre><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px"><button class="btn ghost" @click="scanOpen=false">关闭</button><button class="btn" @click="runScan">开始扫描</button></div></div></div>
  <div v-if="toast" :key="toast" class="toast">{{toast}}</div>
</div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import QRCode from 'qrcode'
import { api } from '../api'
const tax=ref({ageGroups:[],subjects:[],materialCategories:[]}); const materials=ref([]); const loading=ref(false)
const categoryId=ref(null),ageGroupId=ref(null),subjectId=ref(null),source=ref('')
const preview=ref(null),edit=ref(null),editForm=ref({title:'',categoryId:null,ageGroupId:null,subjectId:null}); const toast=ref('')
const qrOpen=ref(false),qrUrl=ref(''); const scanOpen=ref(false),scanResult=ref(null); const scanForm=ref({root:'/data/inbox',categoryId:null,recursive:true})
const filtered=computed(()=>materials.value)
function sourceText(s){return ({phone:'手机上传',scan:'目录扫描',upload:'网页上传'})[s]||s||'未知'}
async function load(){loading.value=true;try{const p=new URLSearchParams({limit:'300'});if(categoryId.value)p.set('categoryId',categoryId.value);if(ageGroupId.value)p.set('ageGroupId',ageGroupId.value);if(subjectId.value)p.set('subjectId',subjectId.value);if(source.value)p.set('source',source.value);const d=await api('/api/v1/admin/materials?'+p);materials.value=d.items||[]}catch(e){toast.value=e.message}finally{loading.value=false}}
async function saveMaterial(){try{await api(`/api/v1/admin/materials/${edit.value.sha256}`,{method:'PATCH',body:editForm.value});edit.value=null;toast.value='素材分类已更新';await load()}catch(e){toast.value=e.message}}
async function removeMaterial(m){if(!confirm(`删除素材「${m.title}」？`))return;try{await api(`/api/v1/admin/materials/${m.sha256}`,{method:'DELETE'});toast.value='素材已删除';await load()}catch(e){toast.value=e.message}}
async function makeQr(){qrUrl.value='';try{const d=await api('/api/v1/admin/upload-tokens',{method:'POST',body:{categoryId:categoryId.value,ageGroupId:ageGroupId.value,subjectId:subjectId.value,maxUploads:20,minutes:30}});qrUrl.value=await QRCode.toDataURL(d.token.url,{width:460,margin:1})}catch(e){toast.value=e.message}}
function showQr(){qrOpen.value=true;makeQr()}
async function runScan(){try{scanResult.value=await api('/api/v1/admin/materials/scan',{method:'POST',body:scanForm.value});toast.value='扫描完成';await load()}catch(e){toast.value=e.message}}
onMounted(async()=>{try{tax.value=await api('/api/v1/admin/taxonomies')}catch(e){toast.value=e.message}await load()})
</script>
