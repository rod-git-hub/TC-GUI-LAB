import subprocess, re, math, logging
logger = logging.getLogger(__name__)
def _run(cmd):
    r=subprocess.run(cmd,capture_output=True,text=True); return r.returncode,r.stdout,r.stderr
def remove_qdisc(iface):
    rc,out,err=_run(["tc","qdisc","del","dev",iface,"root"]); return{"ok":rc in(0,2),"stdout":out,"stderr":err}
def apply_netem(iface,config):
    remove_qdisc(iface)
    lat=float(config.get("latency_ms",0)); jit=float(config.get("jitter_ms",0))
    loss=float(config.get("loss_pct",0)); dup=float(config.get("duplicate_pct",0))
    cor=float(config.get("corrupt_pct",0)); rate=float(config.get("rate_mbit",0))
    if rate>0:
        rc,_,err=_run(["tc","qdisc","add","dev",iface,"root","handle","1:","htb","default","10"])
        if rc!=0: return{"ok":False,"stderr":err}
        rc,_,err=_run(["tc","class","add","dev",iface,"parent","1:","classid","1:10","htb","rate",f"{rate}mbit","burst","15k"])
        if rc!=0: return{"ok":False,"stderr":err}
        netem=["tc","qdisc","add","dev",iface,"parent","1:10","handle","10:","netem"]
    else:
        netem=["tc","qdisc","add","dev",iface,"root","handle","1:","netem"]
    if lat>0:
        netem+=["delay",f"{lat}ms"]
        if jit>0: netem+=[f"{jit}ms","distribution","normal"]
    if loss>0: netem+=["loss",f"{loss}%"]
    if dup>0:  netem+=["duplicate",f"{dup}%"]
    if cor>0:  netem+=["corrupt",f"{cor}%"]
    rc,out,err=_run(netem)
    return{"ok":rc==0,"stdout":out,"stderr":err,"tc_cmd":" ".join(netem)}
def get_qdisc_stats(iface):
    rc,out,err=_run(["tc","-s","qdisc","show","dev",iface]); return{"ok":rc==0,"raw":out,"stderr":err}
def list_interfaces():
    ifaces=[]
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name=line.split(":")[0].strip()
                if name and name!="lo": ifaces.append(name)
    except: pass
    return ifaces
def detect_tc_config(iface):
    rc,out,_=_run(["tc","qdisc","show","dev",iface])
    if rc!=0 or "netem" not in out: return {}
    cfg={}
    m=re.search(r'delay\s+(\d+(?:\.\d+)?)(m?s)',out)
    if m:
        v=float(m.group(1)); cfg["latency_ms"]=v if m.group(2)=="ms" else v*1000
        m2=re.search(r'delay\s+\d+(?:\.\d+)?m?s\s+(\d+(?:\.\d+)?)(m?s)',out)
        if m2: jv=float(m2.group(1)); cfg["jitter_ms"]=jv if m2.group(2)=="ms" else jv*1000
    for pat,key in[(r'loss\s+(\d+(?:\.\d+)?)%',"loss_pct"),
                   (r'duplicate\s+(\d+(?:\.\d+)?)%',"duplicate_pct"),
                   (r'corrupt\s+(\d+(?:\.\d+)?)%',"corrupt_pct")]:
        m=re.search(pat,out)
        if m: cfg[key]=float(m.group(1))
    rc2,out2,_=_run(["tc","class","show","dev",iface])
    mr=re.search(r'rate\s+(\d+(?:\.\d+)?)(K|M|G)?bit',out2)
    if mr:
        v=float(mr.group(1)); u=mr.group(2) or ""
        cfg["rate_mbit"]=v/1000 if u=="K" else v if u=="M" else v*1000 if u=="G" else v/1e6
    return cfg
def detect_all_tc_configs(ifaces):
    return {i:cfg for i in ifaces if(cfg:=detect_tc_config(i))}
def split_config_for_members(config,num_members=2):
    if num_members<=1: return dict(config)
    n=max(1,num_members); out={}
    for key in("latency_ms","jitter_ms"):
        if key in config: out[key]=round(float(config[key])/n,2)
    for key in("loss_pct","duplicate_pct","corrupt_pct"):
        if key in config:
            p=max(0.0,min(0.9999,float(config[key])/100.0))
            out[key]=0.0 if p<=0 else round((1-math.pow(1-p,1/n))*100,4)
    if "rate_mbit" in config: out["rate_mbit"]=float(config["rate_mbit"])
    return out
