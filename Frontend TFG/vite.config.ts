import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(),tailwindcss()],server:{host:'127.0.0.1',port:5174,strictPort:true,proxy:{'/api':{target:process.env.VIBI_BACKEND_URL || 'http://127.0.0.1:8000',ws:true}}},build:{assetsInlineLimit:0}});
