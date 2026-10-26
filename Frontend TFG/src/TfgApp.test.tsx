import {render, screen} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {expect,it,vi,beforeEach} from 'vitest';
import userEvent from '@testing-library/user-event';
import {TfgApp} from './TfgApp';
vi.mock('./components/ChatPanel',()=>({ChatPanel:()=> <div>Chat conectado</div>}));
vi.mock('./pages/EquiposPage',()=>({EquiposPage:()=> <div>Equipos conectados</div>}));
vi.mock('./pages/SkillsPage',()=>({SkillsPage:()=> <div>Skills conectadas</div>}));
vi.mock('./lib/useEvents',()=>({useEvents:()=>{}}));
beforeEach(()=>{localStorage.clear();vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({nodos:[]}),{headers:{'Content-Type':'application/json'}})))});
function mount(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><TfgApp/></MemoryRouter></QueryClientProvider>)}
it('requiere sesión antes de mostrar datos privados',()=>{mount();expect(screen.getByRole('button',{name:'Entrar'})).toBeInTheDocument();expect(screen.queryByText('Chat conectado')).not.toBeInTheDocument()});
it('navega entre las tres funciones y conserva el tema',async()=>{localStorage.setItem('vibi.jwt','test');mount();expect(screen.getByText('Chat conectado')).toBeInTheDocument();await userEvent.click(screen.getByRole('link',{name:'Dispositivos'}));expect(screen.getByText('Equipos conectados')).toBeInTheDocument();await userEvent.click(screen.getByRole('link',{name:'Skill Studio'}));expect(screen.getByText('Skills conectadas')).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'Cambiar a oscuro'}));expect(localStorage.getItem('vibi.tfg.theme')).toBe('dark')});
it('vacía la sesión y los datos al salir',async()=>{localStorage.setItem('vibi.jwt','test');mount();await userEvent.click(screen.getByRole('button',{name:'Cerrar sesión'}));expect(localStorage.getItem('vibi.jwt')).toBeNull();expect(screen.getByRole('button',{name:'Entrar'})).toBeInTheDocument()});
