import {readFileSync} from 'node:fs'
import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import {federation} from '@module-federation/vite'
const manifest = JSON.parse(readFileSync(new URL('../package.v3.json', import.meta.url), 'utf8'))
export default defineConfig(({mode}) => {
  const translate = false
  const name = translate ? 'MetadataTranslate' : 'NfoCheck'
  const directory = translate ? 'metadatatranslate' : 'nfocheck'
  const source = translate ? './src/translate' : './src'
  const version = manifest[name].version
  return {
  base: './',
  plugins: [{name:'plugin-build-version', generateBundle(){this.emitFile({type:'asset',fileName:'assets/build-meta.json',source:JSON.stringify({version,plugin:name})})}}, vue(), federation({name, filename: 'assets/remoteEntry.js', dts: false,
    exposes: {'./Page': source+'/App.vue', './Config': source+'/Config.vue'},
    shared: {vue: {requiredVersion: false, import: false, singleton: true}}})],
  build: {target: 'esnext', outDir: '../plugins.v3/'+directory+'/dist', emptyOutDir: true}
  }
})
