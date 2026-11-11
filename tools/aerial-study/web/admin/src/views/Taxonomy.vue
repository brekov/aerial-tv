<template><div>
<div class="page-head"><div><h1>分类管理</h1><p class="muted">年龄、学科、题型和素材分类</p></div><button @click="load">刷新</button></div>
<div class="panel"><h2>年龄/学段</h2><div class="row"><input v-model="age.code" placeholder="代码，如 grade1"><input v-model="age.name" placeholder="名称，如 一年级"><button @click="add('age-groups',age)">新增</button></div><div class="tags" style="margin-top:10px"><span class="tag" v-for="x in t.ageGroups" :key="x.id">{{ x.name }}</span></div></div>
<div class="panel"><h2>学科/能力</h2><div class="row"><input v-model="subject.code" placeholder="代码，如 literacy"><input v-model="subject.name" placeholder="名称，如 识字"><button @click="add('subjects',subject)">新增</button></div><div class="tags" style="margin-top:10px"><span class="tag" v-for="x in t.subjects" :key="x.id">{{ x.name }}</span></div></div>
<div class="panel"><h2>素材分类</h2><div class="row"><input v-model="category.name" placeholder="分类名称"><button @click="add('material-categories',category)">新增</button></div><div class="tags" style="margin-top:10px"><span class="tag" v-for="x in t.materialCategories" :key="x.id">{{ x.name }}</span></div></div>
<div class="panel"><h2>题型</h2><div class="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>答题方式</th><th>图片</th><th>选项</th></tr></thead><tbody><tr v-for="x in t.questionTypes" :key="x.code"><td>{{ x.code }}</td><td>{{ x.name }}</td><td>{{ x.answer_mode }}</td><td>{{ x.requires_image ? '必需':'可选' }}</td><td>{{ x.min_options }}–{{ x.max_options }}</td></tr></tbody></table></div></div>
<div class="toast" v-if="toast">{{ toast }}</div>
</div></template>
<script setup>
import { reactive, ref, onMounted } from 'vue'
import { api } from '../api'
const t = ref({ ageGroups: [], subjects: [], materialCategories: [], questionTypes: [] })
const age = reactive({ code: '', name: '' }); const subject = reactive({ code: '', name: '' }); const category = reactive({ name: '' })
const toast = ref('')
async function load(){ const d=await api('/api/v1/admin/taxonomies'); t.value=d }
async function add(kind, payload){ try { await api(`/api/v1/admin/${kind}`,{method:'POST',body:payload}); toast.value='已新增'; await load(); payload.name=''; payload.code='' } catch(e){ toast.value=e.message } }
onMounted(()=>load().catch(e=>toast.value=e.message))
</script>
