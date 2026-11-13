"""Filesystem preparation/collection inside the isolated FABulous Linux runtime.

Only administrator-pinned fabric sources and generated model RTL are consumed.
No uploaded Python or user-supplied command is executed here.
"""
import argparse,hashlib,json,shutil,uuid,zipfile
from pathlib import Path,PurePosixPath


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(work,project,profile_path):
    profile=json.loads(profile_path.read_text())
    package=profile_path.with_name(profile['package'])
    if profile['schema']!='bmlabs.fabric-postprocess.v1' or digest(package)!=profile['package_sha256']:
        raise ValueError('Fabric source package integrity mismatch')
    if project.name!=str(uuid.UUID(work.name)) or project.exists():
        raise ValueError('A new, matching build UUID directory is required')
    project.mkdir(parents=True)
    with zipfile.ZipFile(package) as archive:
        if sum(i.file_size for i in archive.infolist())>50*1024*1024:raise ValueError('Fabric source package exceeds quota')
        for info in archive.infolist():
            name=PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or info.is_dir():
                raise ValueError('Unexpected fabric archive path')
            data=archive.read(info)
            if hashlib.sha256(data).hexdigest()!=profile['files'].get(info.filename):
                raise ValueError('Fabric source manifest mismatch: '+info.filename)
            p=project/str(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    for name in profile['files']:
        if not (project/name).is_file():raise ValueError('Incomplete fabric package')
    shutil.copyfile(work/'fabric_model.v',project/'user_design/model_postprocess.v')
    shutil.copyfile(profile_path,work/'fabric_target.json')
    print('BMLABS_FABRIC_PACKAGE_PREPARED '+profile['package_sha256'])


def prepare_cosim(work,project):
    ir=json.loads((work/'ir.json').read_text());vectors=json.loads((work/'vectors.json').read_text())
    rows=len(ir['weights'][0]);cols=len(ir['weights']);count=len(vectors)
    if not 1<=rows<=32 or not 1<=cols<=32 or not 1<=count<=512:raise ValueError('Unsupported model/vector shape')
    sim=project/'Test/prototype';sim.mkdir(exist_ok=False)
    def pack(values):
        b=bytes(v&255 for v in values);b+=bytes((-len(b))%4)
        return [int.from_bytes(b[i:i+4],'little') for i in range(0,len(b),4)]
    weights=pack([ir['weights'][c][r] for r in range(rows) for c in range(cols)])
    inputs=[v for vector in vectors for v in pack(vector['input'])]
    raw=[sum(x*w for x,w in zip(vector['input'],row)) for vector in vectors for row in ir['weights']]
    gold=[v for vector in vectors for v in vector['expected']]
    for name,values in [('weights',weights),('inputs',inputs),('raw',raw),('gold',gold)]:
        (sim/(name+'.hex')).write_text('\n'.join(f'{v&0xffffffff:08x}' for v in values))
    binary=(project/'user_design/model_postprocess.bin').read_bytes()
    if not binary or len(binary)%4 or len(binary)>16384:raise ValueError('Invalid generated FABulous binary')
    padded=binary+bytes(16384-len(binary))
    (sim/'config.hex').write_text('\n'.join(f'{int.from_bytes(padded[i:i+4],"big"):08x}' for i in range(0,16384,4)))
    tb=(work/'fabric_cosim_template.v.in').read_text()
    values={'ROWS':rows,'COLS':cols,'WEIGHTS':len(weights),'WEIGHTS_MINUS':len(weights)-1,
        'INPUT_WORDS':(rows+3)//4,'INPUTS_MINUS':len(inputs)-1,'OUTPUTS_MINUS':len(gold)-1,'VECTORS':count}
    for key,value in values.items():tb=tb.replace('@'+key+'@',str(value))
    (sim/'prototype_tb.v').write_text(tb)
    sources=list((project/'Fabric').rglob('*.v'))
    for tile in ['LUT4AB','RAM_IO','W_IO','N_term_single','S_term_single','N_term_RAM_IO','S_term_RAM_IO']:
        sources.extend(p for p in (project/'Tile'/tile).rglob('*.v') if not(tile=='W_IO' and p.name=='Config_access.v'))
    sources.extend([project/'x2/axi_fabric_shell.v',project/'x2/axi_x2_mvm_accel.sv',sim/'prototype_tb.v'])
    if any(any(c.isspace() for c in str(p)) for p in sources):raise ValueError('Fabric source paths must not contain whitespace')
    (sim/'sources.f').write_text('\n'.join(map(str,sources)))
    (work/'fabric_source_hashes.json').write_text(json.dumps({p.relative_to(project).as_posix():digest(p) for p in sources},indent=2))
    print('BMLABS_FABRIC_COSIM_PREPARED vectors='+str(count))


def collect(work,project):
    if not project.is_dir():return
    profile=json.loads((work/'fabric_target.json').read_text())
    spec=project/'.FABulous/bitStreamSpec.bin'
    if digest(spec)!=profile['files']['.FABulous/bitStreamSpec.bin']:
        raise ValueError('Configuration encoding changed during the model build')
    names={'user_design/model_postprocess.bin':'fabric_model.bin','user_design/model_postprocess.fasm':'fabric_model.fasm',
        'user_design/model_postprocess.json':'fabric_model_mapped.json','Test/prototype/prototype_tb.v':'fabric_cosim_tb.v',
        'Test/prototype/config.hex':'fabric_configuration.hex'}
    for source,target in names.items():
        if (project/source).is_file():shutil.copyfile(project/source,work/target)
    files=[p for p in project.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in files) or sum(p.stat().st_size for p in files)>200*1024*1024:
        raise ValueError('Fabric work package exceeds its uncompressed quota')
    with zipfile.ZipFile(work/'fabric_model_bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(files):archive.write(p,p.relative_to(project).as_posix())
    if (work/'fabric_model_bundle.zip').stat().st_size>40*1024*1024:raise ValueError('Fabric archive exceeds artifact quota')
    print('BMLABS_FABRIC_ARTIFACTS_COLLECTED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','cosim','collect'])
    p.add_argument('--work',required=True);p.add_argument('--project',required=True);p.add_argument('--profile')
    a=p.parse_args();work=Path(a.work);project=Path(a.project)
    if a.stage=='prepare':prepare(work,project,Path(a.profile))
    elif a.stage=='cosim':prepare_cosim(work,project)
    else:collect(work,project)
