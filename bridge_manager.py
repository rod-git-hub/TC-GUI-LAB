import subprocess,json as _json,os as _os,logging,re as _re
logger=logging.getLogger(__name__)
def _run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True); return r.returncode,r.stdout,r.stderr

# Bridges owned by another subsystem. The UI still lists them (you may want to
# impair one), but they are never written to network_config.json and never
# recreated on restore: they belong to Docker/libvirt/LXC, which make their own
# on start, and a bundle that tried to recreate docker0 would fight the daemon.
_FOREIGN_BRIDGE = _re.compile(
    r"^(docker\d+|br-[0-9a-f]{12}|virbr\d+(-nic)?|lxcbr\d+|podman\d+|cni-podman\d+)$")

def is_foreign_bridge(name):
    """True for a bridge another daemon owns (docker0, virbr0, ...)."""
    return bool(_FOREIGN_BRIDGE.match(str(name)))
def _bridges_via_ip():
    rc,out,_=_run(["ip","-j","link","show","type","bridge"]); bridges={}
    if rc!=0 or not out.strip(): return bridges
    try:
        for l in _json.loads(out):
            n=l.get("ifname",""); f=l.get("flags",[])
            bridges[n]={"members":[],"state":"up" if "UP" in f else "down","mtu":l.get("mtu","")}
    except Exception as e: logger.warning("ip bridge: %s",e)
    return bridges
def _bridges_via_sysfs():
    bridges={}
    try:
        for n in _os.listdir("/sys/class/net"):
            if _os.path.isdir(f"/sys/class/net/{n}/bridge"):
                st="unknown"
                try:
                    with open(f"/sys/class/net/{n}/operstate") as f: st=f.read().strip()
                except: pass
                bridges[n]={"members":[],"state":st,"mtu":""}
    except Exception as e: logger.warning("sysfs bridge: %s",e)
    return bridges
def _get_members(br):
    rc,out,_=_run(["ip","-j","link","show","master",br])
    if rc==0 and out.strip():
        try: return [l["ifname"] for l in _json.loads(out) if l.get("ifname")]
        except: pass
    brif=f"/sys/class/net/{br}/brif"
    return _os.listdir(brif) if _os.path.isdir(brif) else []
def get_all_bridges():
    b=_bridges_via_ip()
    if not b: b=_bridges_via_sysfs()
    for n in b: b[n]["members"]=_get_members(n)
    return b
def get_all_link_info():
    rc,out,_=_run(["ip","-j","link","show"])
    try: return _json.loads(out) if rc==0 else []
    except: return []
def list_unbridged_interfaces():
    bnames=set(get_all_bridges().keys()); rc,out,_=_run(["ip","-j","link","show"]); res=[]
    if rc!=0: return res
    try:
        for l in _json.loads(out):
            n=l.get("ifname","")
            if n in("lo","") or n in bnames: continue
            if l.get("link_type")=="loopback": continue
            if not l.get("master"): res.append(n)
    except: pass
    return res
def create_bridge(name,stp=False):
    rc,_,err=_run(["ip","link","add","name",name,"type","bridge"])
    if rc!=0: return{"ok":False,"stderr":err}
    _run(["ip","link","set",name,"type","bridge","stp_state","1" if stp else "0"])
    rc2,_,err2=_run(["ip","link","set",name,"up"])
    try:
        with open("/proc/sys/net/ipv4/ip_forward","w") as f: f.write("1")
    except: pass
    return{"ok":rc2==0,"stderr":err2}
def delete_bridge(name):
    for m in _get_members(name): _run(["ip","link","set",m,"nomaster"])
    _run(["ip","link","set",name,"down"]); rc,_,err=_run(["ip","link","del",name])
    return{"ok":rc==0,"stderr":err}
def add_member(bridge,iface):
    _run(["ip","addr","flush","dev",iface]); _run(["ip","link","set",iface,"up"])
    rc,_,err=_run(["ip","link","set",iface,"master",bridge]); return{"ok":rc==0,"stderr":err}
def remove_member(iface):
    rc,_,err=_run(["ip","link","set",iface,"nomaster"]); return{"ok":rc==0,"stderr":err}
def set_bridge_up(name,up=True):
    rc,_,err=_run(["ip","link","set",name,"up" if up else "down"]); return{"ok":rc==0,"stderr":err}
def get_bridge_stats(name):
    rc,out,err=_run(["ip","-s","link","show",name]); return{"ok":rc==0,"raw":out,"stderr":err}
