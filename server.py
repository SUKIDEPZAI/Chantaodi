import os, json, base64, mimetypes, logging, urllib.request, urllib.parse
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from openai import OpenAI
ROOT=os.path.dirname(os.path.abspath(__file__))
app=Flask(__name__,static_folder=None)
app.config['MAX_CONTENT_LENGTH']=int(os.getenv('MAX_UPLOAD_MB','25'))*1024*1024
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
MODELS=['DeepSeek-V4-Flash-0731','claude-sonnet-4-6','claude-sonnet-5','claude-sonnet-5-5','deepseek-v4-flash','glm-5.3-flash','gpt-5.6-sol','gpt-6-astra','gpt-6-luna','gpt-6-sol','grok-4.5','grok-4.6','hy3','hy4-preview','minimax-m2.7','minimax-m3','qwen3.8-max']

def client():
    key=os.getenv('MOTAPIS_API_KEY','').strip()
    if not key: raise RuntimeError('Chưa cấu hình MOTAPIS_API_KEY trong Render Environment.')
    return OpenAI(api_key=key,base_url=os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1').rstrip('/'),timeout=float(os.getenv('API_TIMEOUT_SECONDS','180')),max_retries=1)

def safe_error(exc):
    status=getattr(exc,'status_code',None); body=getattr(exc,'body',None); raw=str(exc)
    if isinstance(body,dict):
        raw+=' '+' '.join(str(body.get(k,'')) for k in ('code','reason','message','error'))
        if isinstance(body.get('error'),dict): raw+=' '+' '.join(str(body['error'].get(k,'')) for k in ('code','reason','message'))
    upper=raw.upper()
    if 'NOT_ENOUGH_BALANCE' in upper or 'NOT ENOUGH BALANCE' in upper or 'INSUFFICIENT BALANCE' in upper: return 'MộtAPI không đủ số dư. Kiểm tra credit trong dashboard MộtAPI.'
    if status==401:return 'MộtAPI từ chối xác thực. Kiểm tra MOTAPIS_API_KEY trên Render.'
    if status==402:return 'Tài khoản MộtAPI hết số dư hoặc không đủ credit.'
    if status==403:return 'MộtAPI từ chối yêu cầu. Kiểm tra quyền model, số dư và hạn mức.'
    if status==404:return 'Không tìm thấy model hoặc endpoint. Kiểm tra tên model và MOTAPIS_BASE_URL.'
    if status==429:return 'MộtAPI đang giới hạn tốc độ hoặc quota. Hãy thử lại sau.'
    if status and status>=500:return 'Máy chủ MộtAPI hoặc nhà cung cấp model đang gặp lỗi.'
    logging.warning('Provider error type=%s status=%s',type(exc).__name__,status)
    return 'Gọi MộtAPI thất bại. Kiểm tra log Render và quyền model/API key.'

def web_search(query, limit=6):
    key=os.getenv('TAVILY_API_KEY','').strip()
    if not key:return {'available':False,'results':[],'note':'Chưa cấu hình TAVILY_API_KEY'}
    payload=json.dumps({'api_key':key,'query':query[:500],'search_depth':'basic','max_results':max(1,min(int(limit),8)),'include_answer':True}).encode()
    req=urllib.request.Request('https://api.tavily.com/search',data=payload,method='POST',headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=18) as r:data=json.loads(r.read().decode())
        return {'available':True,'answer':data.get('answer',''),'results':[{'title':str(x.get('title',''))[:300],'url':str(x.get('url',''))[:1000],'content':str(x.get('content',''))[:1800]} for x in data.get('results',[])]}
    except Exception as e:
        logging.warning('Web search failed: %s',type(e).__name__);return {'available':False,'results':[],'note':'Tìm kiếm web tạm thời thất bại'}

def extract_file(f):
    name=f.filename or 'file'; raw=f.read(); mime=(f.mimetype or mimetypes.guess_type(name)[0] or '').lower(); ext=os.path.splitext(name)[1].lower()
    text_ext={'.txt','.md','.csv','.json','.py','.js','.ts','.tsx','.jsx','.html','.css','.xml','.yaml','.yml','.log','.sql','.toml','.ini','.sh','.java','.c','.cpp','.h','.go','.rs','.ipynb'}
    if ext in text_ext:return {'kind':'text','name':name,'text':raw.decode('utf-8',errors='replace')[:60000]}
    if ext=='.pdf' or mime=='application/pdf':
        try:
            from pypdf import PdfReader
            return {'kind':'text','name':name,'text':'\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(raw)).pages)[:60000]}
        except Exception:return {'kind':'text','name':name,'text':'[Không trích xuất được PDF.]'}
    if ext=='.docx':
        try:
            from docx import Document
            return {'kind':'text','name':name,'text':'\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)[:60000]}
        except Exception:return {'kind':'text','name':name,'text':'[Không trích xuất được DOCX.]'}
    if mime.startswith('image/') or ext in {'.png','.jpg','.jpeg','.webp','.gif'}:
        mime=mime if mime.startswith('image/') else (mimetypes.guess_type(name)[0] or 'image/jpeg')
        return {'kind':'image','name':name,'url':f'data:{mime};base64,{base64.b64encode(raw).decode()}'}
    return {'kind':'text','name':name,'text':f'[Tệp {name}, {len(raw)} byte; định dạng chưa trích xuất tự động.]'}

@app.get('/')
def home():return send_from_directory(ROOT,'index.html')
@app.get('/api/health')
def health():return jsonify(ok=True,configured=bool(os.getenv('MOTAPIS_API_KEY','').strip()),search_configured=bool(os.getenv('TAVILY_API_KEY','').strip()),provider='MộtAPI',base_url=os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1'))
@app.get('/api/models')
def models():
    key=os.getenv('MOTAPIS_API_KEY','').strip()
    if not key:return jsonify(models=[{'id':m,'available':None} for m in MODELS],source='configured-list')
    try:
        base=os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1').rstrip('/')+'/'
        req=urllib.request.Request(urllib.parse.urljoin(base,'models'),headers={'Authorization':f'Bearer {key}'})
        with urllib.request.urlopen(req,timeout=12) as r:data=json.loads(r.read().decode())
        actual={str(x.get('id')) for x in data.get('data',[]) if isinstance(x,dict) and x.get('id')}; allm=MODELS+[x for x in sorted(actual) if x not in MODELS]
        return jsonify(models=[{'id':m,'available':m in actual if actual else None} for m in allm],source='provider-model-list' if actual else 'configured-list')
    except Exception as e:logging.warning('Model list unavailable: %s',type(e).__name__);return jsonify(models=[{'id':m,'available':None} for m in MODELS],source='configured-list')
@app.post('/api/search')
def search_route():
    d=request.get_json(silent=True) or {}; q=str(d.get('query','')).strip()
    if not q:return jsonify(error='Nhập từ khóa cần tìm.'),400
    r=web_search(q,d.get('max_results',5))
    if not r['available']:return jsonify(error='Tìm kiếm web chưa được cấu hình. Thêm TAVILY_API_KEY trong Render Environment.'),503
    return jsonify(r)
@app.post('/api/chat')
def chat():
    message=request.form.get('message','').strip(); model=request.form.get('model','gpt-6-astra').strip(); mode=request.form.get('mode','chat'); use_search=request.form.get('web_search','false').lower()=='true'
    if not model or len(model)>120:return jsonify(error='Tên model không hợp lệ.'),400
    try:history=json.loads(request.form.get('history','[]')); history=history if isinstance(history,list) else []
    except Exception:history=[]
    try:files=[extract_file(f) for f in request.files.getlist('files') if f.filename]
    except Exception:return jsonify(error='Không đọc được một tệp đính kèm.'),400
    prompt=message or 'Hãy xem xét các tệp/ảnh đính kèm và hỗ trợ tôi.'; user=[{'type':'text','text':prompt}]
    for f in files:
        if f['kind']=='image':user.append({'type':'image_url','image_url':{'url':f['url']}})
        else:user[0]['text']+=f"\n\n--- Tệp: {f['name']} ---\n{f['text']}"
    search=web_search(message,6) if use_search and message else None
    if search and search.get('available'):
        refs=['KẾT QUẢ TÌM KIẾM WEB. Hãy kiểm chứng, không bịa thêm nguồn:']
        if search.get('answer'):refs.append('Tóm tắt tìm kiếm: '+str(search['answer'])[:2500])
        refs += [f"[{i}] {x['title']}\nURL: {x['url']}\nNội dung: {x['content']}" for i,x in enumerate(search.get('results',[]),1)]
        user[0]['text']+='\n\n'+'\n\n'.join(refs)
    system=os.getenv('AI_SYSTEM_PROMPT','Bạn là trợ lý AI hữu ích, chính xác. Trả lời tiếng Việt khi phù hợp. Với code: đưa kế hoạch ngắn, mã rõ ràng, file cần sửa, cách chạy và kiểm thử; không khẳng định đã chạy test nếu chưa chạy. Không tiết lộ chuỗi suy nghĩ nội bộ riêng tư; hãy cung cấp giải thích ngắn, kết luận, giả định và bước kiểm chứng. Nếu có nguồn web, dẫn link và tiêu đề.')
    if mode=='coding':system+='\nChế độ CODING: làm việc như kỹ sư phần mềm, xem xét lỗi, bảo mật, patch, test, hướng dẫn deploy; chia đầu việc thành các bước có thể kiểm chứng.'
    if mode=='research':system+='\nChế độ RESEARCH: ưu tiên nguồn mới, đối chiếu dữ kiện, phân biệt điều đã xác minh và suy luận; kèm URL nguồn.'
    msgs=[{'role':'system','content':system}]
    for h in history[-20:]:
        if isinstance(h,dict) and h.get('role') in ('user','assistant') and isinstance(h.get('content'),str):msgs.append({'role':h['role'],'content':h['content'][:20000]})
    msgs.append({'role':'user','content':user})
    def event(d):return 'data: '+json.dumps(d,ensure_ascii=False)+'\n\n'
    @stream_with_context
    def generate():
        try:
            if use_search:
                yield event({'status':'Đã tìm và thêm nguồn web vào ngữ cảnh.' if search and search.get('available') else 'Tìm kiếm web chưa sẵn sàng; câu trả lời có thể chỉ dựa trên kiến thức của model.'})
            yield event({'status':'Đang phân tích yêu cầu và chuẩn bị câu trả lời.' if mode=='chat' else ('Đang đối chiếu nguồn và tổng hợp thông tin.' if mode=='research' else 'Đang lập kế hoạch kỹ thuật và chuẩn bị lời giải code.')})
            stream=client().chat.completions.create(model=model,messages=msgs,stream=True,temperature=float(os.getenv('AI_TEMPERATURE','0.7')),max_tokens=int(os.getenv('AI_MAX_TOKENS','4096')))
            for chunk in stream:
                if not chunk.choices:continue
                c=getattr(chunk.choices[0].delta,'content',None)
                if isinstance(c,str) and c:yield event({'token':c})
                elif isinstance(c,list):
                    for b in c:
                        t=getattr(b,'text',None)
                        if t:yield event({'token':t})
            yield event({'done':True,'model':model,'searched':bool(search and search.get('available'))})
        except Exception as e:logging.warning('MộtAPI failed (%s)',type(e).__name__);yield event({'error':safe_error(e)})
    return Response(generate(),mimetype='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','Connection':'keep-alive'})
@app.errorhandler(413)
def too_large(_):return jsonify(error=f"Tệp vượt giới hạn {app.config['MAX_CONTENT_LENGTH']//(1024*1024)} MB. Chỉnh MAX_UPLOAD_MB trên Render nếu cần."),413
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
