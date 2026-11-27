"""M0 authorized later-edit regression control on a known functional fixture."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import mini
from m0_characterize import initialize, leaf, tool, js, behavior, dump, digest, summarize


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--browser-executable',type=Path,required=True)
    a=p.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    provenance=json.loads((a.source_run/'provenance.json').read_text())
    source=provenance['source_contract'];workspace=out/'workspace'
    initialize(workspace,source);mini._load_optional_imports()
    for name in ('index.html','style.css','app.js'):
        (workspace/name).write_bytes((a.source_run/'chain_full/workspace'/name).read_bytes())
    before={name:digest(workspace/name) for name in ('index.html','style.css','app.js')}
    task=mini.make_task('3','Update task-list behavior while preserving adding, completion, deletion and persistence.',
                        1,'ROOT',['Preserve all existing interactions after the authorized script update.'],['app.js'])
    mini.TASKS['3']=task
    actions=[tool('read_file',path='app.js'),tool('edit_file',path='app.js',old=js('full'),new=js('no_delete')),
             tool('run_command',command='node --check app.js')]
    with patch.object(mini,'browser_launch_kwargs',return_value={'headless':True,'executable_path':str(a.browser_executable)}), \
         patch.object(mini,'http_post_json',side_effect=AssertionError('No provider HTTP')), \
         patch.object(mini,'http_get_json',side_effect=AssertionError('No provider HTTP')):
        prior=behavior(workspace,a.browser_executable)
        result,calls=leaf(task,source,actions,{})
        after=behavior(workspace,a.browser_executable)
    record={'fixture_scope':'Seeded byte-identical from the real controlled chain output, not a resumed model run or fabricated predecessor receipt.',
            'source_run':str(a.source_run),'before_hashes':before,'before_behavior':prior,'result':summarize(result),
            'model_calls':calls,'after_behavior':after,'after_hashes':{n:digest(workspace/n) for n in before},
            'argv':sys.argv,'source_head':provenance['head'],'python':sys.version,'harness_sha256':digest(__file__)}
    dump(out/'result.json',record)
    print('REGRESSION_CONTROL before_behavior=',prior['passed'],'native_child=',result['status'],'after_behavior=',after['passed'])
    return 0


if __name__=='__main__':raise SystemExit(main())
