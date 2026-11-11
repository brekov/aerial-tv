<template><div>
<div class="page-head"><div><h1>素材库</h1><p class="muted">手机扫码上传、目录扫描、分类整理</p></div><div class="row"><button @click="openQr">手机扫码上传</button><button class="ghost" @click="load">刷新</button></div></div>
<div class="panel"><div class="row"><label class="grow">分类<select v-model="filter.categoryId"><option :value="null">全部</option><option v-for="x in t.materialCategories" :key="x.id" :value="x.id">{{x.name}}</option></select></label><label class="grow">来源<select v-model="filter.source"><option value="">全部</option><option value="upload">本地上传</option><option value="mobile">手机上传</option><option value="scan">目录扫描</option></select></label><button @click="load">筛选</button></div></div>
<div class="panel"><h2>目录扫描</h2><div class="row"><input class="grow" v-model="scan.root" placeholder="NAS 扫描目录，如 /data/inbox"><label>分类<select v-model="scan.categoryId"><option :value="null">未分类</option><option v-for="x in t.materialCategories" :key="x.id" :value="x.id">{{x.name}}</option></select></label><button @click="doScan">开始扫描</button></div><p class="muted" v-if="scanResult">{{ scanResult }}</p></div>
<div class="panel"><div class="grid"><figure v-for="m in items" :key="m.sha256" style="margin:0"><img class="thumb" :src="m.url" :alt="m.title"><figcaption><div>{{ m.title || m.filename }}</div><span class="muted">{{ m.source }} · {{ m.kind }}</span></figcaption></figure></div><p v-if="!items.length" class="muted">暂无素材</p></div>
<div v-if="qr" class="panel"><h2>手机上传二维码</h2><img class="qr" :src="qr"><p class="muted" style="text-align:center;word-break:break-all">{{ qrUrl }}</p><p class="muted" style="text-align:center">有效期 {{ tokenInfo?.expiresAt }}</p><div class="row" style="justify-content:center"><button class="ghost" @click="openQr">刷新二维码</button><button class="ghost" @click="qr=''">关闭</button></div></div>
<div class="toast" v-if="toast">{{ toast }}</div></div></template>
<script setup>
import { reactive, ref, onMounted } from 'vue'
import QRCode from 'qrcode'
import { api } from '../api'
const t=ref({materialCategories:[]}); const items=ref([]); const filter=reactive({categoryId:null,source:''}); const scan=reactive({root:'',categoryId:null}); const scanResult=ref(''); const qr=ref(''); const qrUrl=ref(''); const tokenInfo=ref(null); const toast=ref('')
async function load(){ const qs=new URLSearchParams(); if(filter.categoryId) qs.set('categoryId',filter.categoryId); if(filter.source) qs.set('source',filter.source); const d=await api('/api/v1/admin/materials?'+qs); items.value=d.items }
async function doScan(){ try{ const d=await api('/api/v1/admin/materials/scan',{method:'POST',body:{root:scan.root,categoryId:scan.categoryId,recursive:true}}); scanResult.value=`新增 ${d.created}，已存在 ${d.existing}，失败 ${d.errors.length}`; await load() }catch(e){toast.value=e.message} }
async function openQr(){ try{ const d=await api('/api/v1/admin/upload-tokens',{method:'POST',body:{categoryId:filter.categoryId}}); tokenInfo.value=d.token; qrUrl.value=d.token.url; qr.value=await QRCode.toDataURL(d.token.url,{width:320,margin:1}) }catch(e){toast.value=e.message} }
onMounted(async()=>{ try{ t.value=await api('/api/v1/admin/taxonomies'); await load() }catch(e){toast.value=e.message} })
</script>
