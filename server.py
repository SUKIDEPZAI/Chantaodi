import os, json, base64, mimetypes, logging
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from openai import OpenAI

ROOT=os.path.dirname(os.path.abspath(__file__))
app=Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH']=int(os.getenv('MAX_UPLOAD_MB','25'))*1024*1024
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
MODELS=['DeepSeek-V4-Flash-0731','claude-sonnet-4-6','claude-sonnet-5','claude-sonnet-5-5','deepseek-v4-flash','glm-5.3-flash','gpt-5.6-sol','gpt-6-astra','gpt-6-luna','gpt-6-sol','grok-4.5','grok-4.6','hy3','hy4-preview','minimax-m2.7','minimax-m3','qwen3.8-max']

def client():
    key=os.getenv('MOTAPIS_API_KEY','').strip()
    if not key: raise RuntimeError('Chưa cấu hình MOTAPIS_API_KEY trong Render Environment.')
    return OpenAI(api_key=key,base_url=os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1').rstrip('/'),timeout=float(os.getenv('API_TIMEOUT_SECONDS','180')),max_retries=1)

def friendly_error(exc):
    status=getattr(exc,'status_code',None); body=getattr(exc,'body',None); raw=str(exc)
    if isinstance(body,dict):
        raw+=' '+str(body.get('code',''))+' '+str(body.get('reason',''))+' '+str(body.get('message',''))+' '+str(body.get('error',''))
        if isinstance(body.get('error'),dict): raw+=' '+str(body['error'])
    u=raw.upper()
    if any(x in u for x in ['NOT_ENOUGH_BALANCE','INSUFFICIENT BALANCE','NOT ENOUGH BALANCE']): return 'MộtAPI không đủ số dư cho yêu cầu. Kiểm tra credit trong dashboard MộtAPI.'
    if status==401:return 'MộtAPI từ chối xác thực. Kiểm tra MOTAPIS_API_KEY trong Render Environment.'
    if status==402:return 'Tài khoản MộtAPI hết số dư hoặc không đủ credit cho model này.'
    if status==403:return 'MộtAPI từ chối yêu cầu. Kiểm tra quyền model, số dư và hạn mức API key.'
    if status==404:return 'Không tìm thấy model hoặc endpoint. Kiểm tra tên model và MOTAPIS_BASE_URL.'
    if status==429:return 'MộtAPI đang giới hạn tốc độ hoặc quota. Chờ một chút rồi thử lại.'
    if status and status>=500:return 'Máy chủ MộtAPI hoặc nhà cung cấp model đang gặp lỗi tạm thời.'
    return 'Gọi MộtAPI thất bại. Kiểm tra log Render và trạng thái API key/model.'

def extract_file(f):
    name=f.filename or 'file'; raw=f.read(); mime=(f.mimetype or mimetypes.guess_type(name)[0] or '').lower(); ext=os.path.splitext(name)[1].lower()
    if ext in {'.txt','.md','.csv','.json','.py','.js','.ts','.tsx','.jsx','.html','.css','.xml','.yaml','.yml','.log','.sql','.toml','.ini','.sh','.java','.c','.cpp','.h','.go','.rs'}:
        return {'kind':'text','name':name,'text':raw.decode('utf-8',errors='replace')}
    if ext=='.pdf' or mime=='application/pdf':
        try:
            from pypdf import PdfReader
            return {'kind':'text','name':name,'text':'\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(raw)).pages)}
        except Exception:return {'kind':'text','name':name,'text':'[Không trích xuất được nội dung PDF.]'}
    if ext=='.docx':
        try:
            from docx import Document
            return {'kind':'text','name':name,'text':'\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)}
        except Exception:return {'kind':'text','name':name,'text':'[Không trích xuất được nội dung DOCX.]'}
    if mime.startswith('image/') or ext in {'.png','.jpg','.jpeg','.webp','.gif'}:
        mime=mime if mime.startswith('image/') else (mimetypes.guess_type(name)[0] or 'image/jpeg')
        return {'kind':'image','name':name,'url':'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')}
    return {'kind':'text','name':name,'text':f'[Tệp {name}, {len(raw)} byte: chưa hỗ trợ trích xuất tự động.]'}

@app.get('/')
def home(): return send_from_directory(ROOT,'index.html')
@app.get('/api/health')
def health(): return jsonify(ok=True,configured=bool(os.getenv('MOTAPIS_API_KEY','').strip()),provider='MộtAPI')
@app.get('/api/models')
def models():
    key=os.getenv('MOTAPIS_API_KEY','').strip(); available=None
    if key:
        try:
            import urllib.request
            req=urllib.request.Request(os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1').rstrip('/')+'/models',headers={'Authorization':'Bearer '+key})
            with urllib.request.urlopen(req,timeout=10) as r: data=json.loads(r.read().decode())
            ids={str(x.get('id')) for x in data.get('data',[]) if isinstance(x,dict) and x.get('id')}
            available=ids if ids else None
        except Exception: pass
    return jsonify(models=[{'id':m,'available':(m in available) if available else None} for m in MODELS])
@app.post('/api/chat')
def chat():
    message=request.form.get('message','').strip(); model=request.form.get('model','gpt-6-astra').strip()
    if model not in MODELS:return jsonify(error='Model không nằm trong danh sách được website cho phép.'),400
    try:
        history=json.loads(request.form.get('history','[]')); history=history if isinstance(history,list) else []
    except Exception:history=[]
    try: attachments=[extract_file(f) for f in request.files.getlist('files') if f.filename]
    except Exception:return jsonify(error='Không đọc được một trong các tệp đính kèm.'),400
    prompt=message or 'Hãy xem xét các tệp/ảnh đính kèm và hỗ trợ tôi.'
    content=[{'type':'text','text':prompt}]
    for a in attachments:
        if a['kind']=='image':content.append({'type':'image_url','image_url':{'url':a['url']}})
        else:content[0]['text']+='\n\n--- Tệp: '+a['name']+' ---\n'+a['text']
    msgs=[{'role':'system','content':os.getenv('AI_SYSTEM_PROMPT','Bạn là trợ lý AI hữu ích. Trả lời bằng tiếng Việt khi phù hợp.')}]
    for m in history[-16:]:
        if isinstance(m,dict) and m.get('role') in ('user','assistant') and isinstance(m.get('content'),str):msgs.append({'role':m['role'],'content':m['content'][:16000]})
    msgs.append({'role':'user','content':content})
    def ev(d):return 'data: '+json.dumps(d,ensure_ascii=False)+'\n\n'
    @stream_with_context
    def generate():
        try:
            stream=client().chat.completions.create(model=model,messages=msgs,stream=True,temperature=float(os.getenv('AI_TEMPERATURE','0.7')),max_tokens=int(os.getenv('AI_MAX_TOKENS','4096')))
            for chunk in stream:
                if not chunk.choices:continue
                delta=chunk.choices[0].delta; value=getattr(delta,'content',None)
                if isinstance(value,str) and value:yield ev({'token':value})
                elif isinstance(value,list):
                    for block in value:
                        txt=getattr(block,'text',None)
                        if txt:yield ev({'token':txt})
            yield ev({'done':True,'model':model})
        except Exception as e:
            app.logger.warning('Provider request failed (%s)',type(e).__name__)
            yield ev({'error':friendly_error(e)})
    return Response(generate(),mimetype='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','Connection':'keep-alive'})
@app.errorhandler(413)
def too_large(_):return jsonify(error=f'Tệp vượt giới hạn {app.config["MAX_CONTENT_LENGTH"]//(1024*1024)} MB mỗi yêu cầu. Có thể chỉnh MAX_UPLOAD_MB trên Render.'),413
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
