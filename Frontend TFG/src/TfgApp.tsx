import {useEffect,useState,type FormEvent} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {NavLink,Navigate,Route,Routes,useNavigate} from 'react-router-dom';
import {MessageSquare,Monitor,Layers,Moon,Sun,LogOut} from 'lucide-react';
import {ChatPanel} from './components/ChatPanel';
import {EquiposPage} from './pages/EquiposPage';
import {SkillsPage} from './pages/SkillsPage';
import {apiFetch} from './lib/api';
import {getToken,setToken,clearToken} from './lib/auth';
import {fetchNodos,nodosKey} from './lib/nodos';
import {useEvents} from './lib/useEvents';
import {estadoCanalActual,suscribirCanal} from './lib/eventBus';

function Login(){const navigate=useNavigate();const cache=useQueryClient();const [error,setError]=useState('');const [pending,setPending]=useState(false);
async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const data=new FormData(e.currentTarget);setPending(true);setError('');try{const result=await apiFetch<{token:string}>('/api/auth/login',{method:'POST',body:JSON.stringify({nombre:data.get('name'),contraseña:data.get('password')})});cache.clear();setToken(result.token);navigate('/',{replace:true})}catch(err){setError(err instanceof Error?err.message:'No se pudo iniciar sesión')}finally{setPending(false)}}
return <main className="tfg-login"><form onSubmit={submit}><div className="tfg-wordmark"><img src="/fox-wizard.png" alt="Zorro de Vibi"/>vibi<span>TFG</span></div><h1>Tu espacio, en cualquier equipo.</h1><p>Accede con tu cuenta de Vibi.</p><label>Nombre<input name="name" autoComplete="username" required/></label><label>Contraseña<input name="password" type="password" autoComplete="current-password" required/></label>{error&&<p role="alert">{error}</p>}<button className="primary-button" disabled={pending}>{pending?'Entrando…':'Entrar'}</button></form></main>}
function Shell(){useEvents();const cache=useQueryClient();const navigate=useNavigate();const [channel,setChannel]=useState(estadoCanalActual);useEffect(()=>suscribirCanal(setChannel),[]);const [theme,setTheme]=useState(()=>localStorage.getItem('vibi.tfg.theme')==='dark'?'dark':'light');useEffect(()=>{document.documentElement.dataset.theme=theme;localStorage.setItem('vibi.tfg.theme',theme)},[theme]);
const nodes=useQuery({queryKey:nodosKey,queryFn:fetchNodos,refetchInterval:15000});
const logout=()=>{clearToken();cache.clear();navigate('/login',{replace:true})};
return <div className="tfg-shell"><aside className="tfg-sidebar"><div className="tfg-wordmark"><img src="/fox-wizard.png" alt="Zorro de Vibi"/>vibi<span>TFG</span></div><nav aria-label="Navegación principal"><NavLink to="/" end><MessageSquare size={20}/>Chat</NavLink><NavLink to="/dispositivos"><Monitor size={20}/>Dispositivos</NavLink><NavLink to="/skills"><Layers size={20}/>Skill Studio</NavLink></nav><p className="tfg-sidebar-note">Tu conversación y tus herramientas, en el mismo espacio.</p><div className="tfg-account"><button onClick={()=>setTheme(theme==='light'?'dark':'light')} aria-label={theme==='light'?'Cambiar a oscuro':'Cambiar a claro'}>{theme==='light'?<Moon size={18}/>:<Sun size={18}/>}</button><button onClick={logout} aria-label="Cerrar sesión"><LogOut size={18}/></button></div></aside><main className="tfg-main"><header className="tfg-header"><strong>Tu espacio</strong><span>{nodes.isError?'No se pudieron consultar los equipos':nodes.data?`${nodes.data.filter(n=>n.conectado).length} equipos disponibles`:'Consultando equipos…'}</span><small role="status">{channel==='conectado'?'En directo':channel==='caido'?'Reconectando…':'Conectando…'}</small></header><div className="tfg-content"><Routes><Route index element={<ChatPanel/>}/><Route path="dispositivos" element={<EquiposPage/>}/><Route path="skills" element={<SkillsPage/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Routes></div></main></div>}
export function TfgApp(){const cache=useQueryClient();const navigate=useNavigate();useEffect(()=>{const unauthorized=()=>{cache.clear();navigate('/login',{replace:true})};window.addEventListener('vibi:unauthorized',unauthorized);return()=>window.removeEventListener('vibi:unauthorized',unauthorized)},[cache,navigate]);return <Routes><Route path="/login" element={<Login/>}/><Route path="*" element={getToken()?<Shell/>:<Navigate to="/login" replace/>}/></Routes>}

