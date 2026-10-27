import ast, pathlib, unittest, time, contextlib,io
ROOT=pathlib.Path(__file__).resolve().parents[1]
def funcs(repo):
    path=ROOT/'tn-service/services/api/app/main.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    code=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and not n.decorator_list],type_ignores=[])
    env={'time':time};exec(compile(code,str(path),'exec'),env)
    return env
class CallbackTests(unittest.TestCase):
    def test_main_uses_short_index_old_copy_uses_text(self):
        for repo in ['tg_logist']:
            e=funcs(repo);e['_suggest_values']=lambda *args:['Длинная локация: '+('А'*300)]
            payload=e['build_unload_kb'](7)['inline_keyboard'][0][0]['callback_data']
            self.assertEqual(payload=='set_unload:7:0',repo=='tg_logist')
    def test_payload_dict_and_callback_aliases(self):
        e=funcs('tg_logist')
        self.assertEqual(e['_extract_callback_meta']({'chat_id':1,'callback':{'data':{'value':'back:7'},'id':'c'}}),(1,'back:7','c',None))
    def test_bad_index_does_not_mutate(self):
        e=funcs('tg_logist');saved=[];shown=[]
        e.update(answer_max_callback=lambda *a:None,_suggest_values=lambda *a:['A'],update_field=lambda *a:saved.append(a),_show_message=lambda *a:shown.append(a))
        e['handle_callback'](1,'set_unload:7:99','c','m')
        self.assertEqual(saved,[]);self.assertTrue(shown)
    def test_new_index_resolves_value(self):
        e=funcs('tg_logist');saved=[]
        e.update(answer_max_callback=lambda *a:None,_suggest_values=lambda *a:['A:B'],update_field=lambda *a:saved.append(a),_render_doc=lambda *a:None)
        e['handle_callback'](1,'set_unload:7:0','c','m');self.assertEqual(saved,[(7,'unloading_address','A:B')])
    def test_negative_index_is_rejected(self):
        e=funcs('tg_logist');saved=[]
        e.update(answer_max_callback=lambda *a:None,_suggest_values=lambda *a:['A'],update_field=lambda *a:saved.append(a),_render_doc=lambda *a:None,_show_message=lambda *a:None)
        e['handle_callback'](1,'set_unload:7:-1','c','m');self.assertEqual(saved,[])
    def test_old_text_payload_is_no_longer_compatible(self):
        e=funcs('tg_logist');saved=[];shown=[]
        e.update(answer_max_callback=lambda *a:None,_suggest_values=lambda *a:['A'],update_field=lambda *a:saved.append(a),_show_message=lambda *a:shown.append(a))
        e['handle_callback'](1,'set_unload:7:A','c','m');self.assertEqual(saved,[]);self.assertTrue(shown)
if __name__=='__main__':unittest.main(verbosity=2)
