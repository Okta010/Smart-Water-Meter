window.API_BASE_URL = 'http://127.0.0.1:8000/api';
window.api = {
 async request(path, options={}) { const r=await fetch(`${window.API_BASE_URL}${path}`,{credentials:'include',...options});const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.detail||'Permintaan gagal');return data; },
 register(payload){return this.request('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})},
 login(identifier,password){return this.request('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier,password})})},
 me(){return this.request('/me')},
 logout(){return this.request('/logout',{method:'POST'})},
 pelanggan(){return this.request('/pelanggan')},
 riwayat(){return this.request('/riwayat')}
};
