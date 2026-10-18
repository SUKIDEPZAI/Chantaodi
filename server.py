import os, re, json, base64, mimetypes, logging, urllib.request, urllib.parse, html
from html.parser import HTMLParser
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

class DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.results=[]; self.cur=None; self.capture=None; self.buf=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs); cls=a.get('class','')
        if tag=='a' and 'result__a' in cls:
            self.cur={'title':'','url':a.get('href',''),'content':''}; self.capture='title'; self.buf=[]
        elif self.cur and tag=='a' and 'result__snippet' in cls:
            self.capture='content'; self.buf=[]
        elif self.cur and tag=='div' and 'result__snippet' in cls:
            self.capture='content'; self.buf=[]
    def handle_data(self,data):
        if self.cur is not None and self.capture:self.buf.append(data)
    def handle_endtag(self,tag):
        if self.cur is None:return
        if tag=='a' and self.capture=='title':
            self.cur['title']=' '.join(''.join(self.buf).split()); self.capture=None; self.buf=[]
            if self.cur['title'] and self.cur['url']: self.results.append(self.cur); self.cur=None
        elif self.capture=='content' and tag in ('a','div'):
            # Snippet can appear after title; associate it with the most recent result.
            if self.results and not self.results[-1].get('content'): self.results[-1]['content']=' '.join(''.join(self.buf).split())
            self.capture=None; self.buf=[]

def _clean_html(value):
    value=re.sub(r'<script\b[^>]*>[\s\S]*?</script>', ' ', value, flags=re.I)
    value=re.sub(r'<style\b[^>]*>[\s\S]*?</style>', ' ', value, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', ' ', value)).replace('\xa0',' ').strip()

def _search_ddg(query, limit):
    url='https://html.duckduckgo.com/html/?q='+urllib.parse.quote(query[:500])
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept-Language':'vi,en;q=0.8'})
    with urllib.request.urlopen(req,timeout=12) as r: page=r.read().decode('utf-8','replace')
    out=[]
    for href,title,snippet in re.findall(r'<a[^>]+class=["\']result__a["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>(.*?)(?=<div class=["\']result|</div>\s*</div>)',page,re.I|re.S):
        href=html.unescape(href); title=_clean_html(title); snippet=_clean_html(snippet)
        if 'uddg=' in href:
            try: href=urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get('uddg',[href])[0]
            except Exception: pass
        if href.startswith('//'): href='https:'+href
        if title and href.startswith('http'): out.append({'title':title[:300],'url':href[:1000],'content':snippet[:1800],'provider':'DuckDuckGo'})
        if len(out)>=limit: break
    return out

def _search_wikipedia(query, limit):
    url='https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode({'action':'query','list':'search','srsearch':query[:300],'format':'json','srlimit':min(limit,5)})
    req=urllib.request.Request(url,headers={'User-Agent':'MotAPIStudio/2.0 (web research)'})
    with urllib.request.urlopen(req,timeout=8) as r:data=json.loads(r.read().decode())
    return [{'title':x.get('title',''),'url':'https://en.wikipedia.org/wiki/'+urllib.parse.quote(x.get('title','').replace(' ','_')),'content':_clean_html(x.get('snippet',''))[:1000],'provider':'Wikipedia'} for x in data.get('query',{}).get('search',[]) if x.get('title')]

def _search_bing(query, limit):
    url='https://www.bing.com/search?'+urllib.parse.urlencode({'q':query[:500]})
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept-Language':'vi,en;q=0.8'})
    with urllib.request.urlopen(req,timeout=10) as r:page=r.read().decode('utf-8','replace')
    out=[]
    for href,title,snippet in re.findall(r'<li class="b_algo"[\s\S]*?<h2><a href="(https?://[^" ]+)"[^>]*>(.*?)</a></h2>([\s\S]*?)(?=<li class="b_algo"|<ol id="b_results")',page,re.I):
        title=_clean_html(title); snippet=_clean_html(snippet)
        if title and href.startswith('http'):out.append({'title':title[:300],'url':html.unescape(href)[:1000],'content':snippet[:1800],'provider':'Bing'})
        if len(out)>=limit:break
    return out

def _search_google_news(query, limit):
    url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query[:300],'hl':'vi','gl':'VN','ceid':'VN:vi'})
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; MotAPIStudio/2.0)'})
    with urllib.request.urlopen(req,timeout=10) as r: raw=r.read()
    import xml.etree.ElementTree as ET
    root=ET.fromstring(raw);out=[]
    for item in root.findall('.//item')[:min(limit,6)]:
        title=item.findtext('title','').strip();link=item.findtext('link','').strip();desc=_clean_html(item.findtext('description',''))
        if title and link.startswith('http'):out.append({'title':title[:300],'url':link[:1000],'content':desc[:1400],'provider':'Google News'})
    return out

def web_search(query, limit=6):
    
    try: limit=max(1,min(int(limit),10))
    except (TypeError,ValueError): limit=6
    query=str(query or '').strip()[:500]
    if not query:return {'available':False,'provider':'none','results':[],'note':'Nhập từ khóa tìm kiếm.'}
    results=[]; providers=[]; errors=[]
    key=os.getenv('TAVILY_API_KEY','').strip()
    if key:
        try:
            payload=json.dumps({'api_key':key,'query':query,'search_depth':'basic','max_results':limit,'include_answer':True}).encode()
            req=urllib.request.Request('https://api.tavily.com/search',data=payload,method='POST',headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=12) as r:data=json.loads(r.read().decode())
            results.extend([{'title':str(x.get('title',''))[:300],'url':str(x.get('url',''))[:1000],'content':str(x.get('content',''))[:1800],'provider':'Tavily'} for x in data.get('results',[])[:limit]])
            providers.append('Tavily')
        except Exception as e:logging.warning('Tavily search failed: %s',type(e).__name__);errors.append('Tavily')
    # Search providers are independent and run concurrently; public HTML endpoints may rate-limit.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    funcs=[('DuckDuckGo',_search_ddg),('Bing',_search_bing),('Wikipedia',_search_wikipedia),('Google News',_search_google_news)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(fn,query,limit):name for name,fn in funcs}
        for future in as_completed(futures,timeout=14):
            name=futures[future]
            try:
                found=future.result()
                if found:results.extend(found);providers.append(name)
                else:errors.append(name)
            except Exception as e:logging.info('%s search unavailable: %s',name,type(e).__name__);errors.append(name)
    seen=set(); unique=[]
    for x in results:
        url=str(x.get('url','')).strip(); title=str(x.get('title','')).strip()
        if not url.startswith('http') or not title:continue
        keyurl=urllib.parse.urlparse(url)._replace(query='',fragment='').geturl().rstrip('/').lower()
        if keyurl in seen:continue
        seen.add(keyurl);unique.append(x)
        if len(unique)>=limit:break
    return {'available':bool(unique),'provider':' + '.join(dict.fromkeys(providers)) if providers else 'none','providers':list(dict.fromkeys(providers)),'answer':'','results':unique,'note':'' if unique else 'Không lấy được kết quả từ các công cụ công khai. Có thể mạng Render bị chặn hoặc các công cụ đang giới hạn truy cập.','failed_providers':errors}

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
def health():
    return jsonify(ok=True,configured=bool(os.getenv('MOTAPIS_API_KEY','').strip()),search_configured=True,search_provider='Tavily + DuckDuckGo + Bing + Wikipedia + Google News' if os.getenv('TAVILY_API_KEY','').strip() else 'DuckDuckGo + Bing + Wikipedia + Google News (không cần key tìm kiếm)',provider='MộtAPI',base_url=os.getenv('MOTAPIS_BASE_URL','https://motapis.com/v1'))

@app.post('/api/diagnostics')
def diagnostics():
    # Safe, explicit smoke test: sends a tiny prompt to the selected provider/model.
    d=request.get_json(silent=True) or {}; model=str(d.get('model') or 'gpt-6-astra').strip()[:120]
    try:
        c=client(); result=c.chat.completions.create(model=model,messages=[{'role':'user','content':'Reply with exactly: OK'}],max_tokens=8,stream=False)
        answer=(result.choices[0].message.content or '').strip() if result.choices else ''
        return jsonify(ok=True,model=model,reply=answer[:80],provider='MộtAPI')
    except Exception as e:
        logging.warning('API diagnostics failed (%s)',type(e).__name__)
        return jsonify(ok=False,model=model,error=safe_error(e),error_type=type(e).__name__,status=getattr(e,'status_code',None)),502
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
    if not r['available']:return jsonify(error=r.get('note') or 'Tìm kiếm công khai tạm thời không khả dụng.'),503
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
        refs=['KẾT QUẢ TÌM KIẾM WEB ('+str(search.get('provider','web'))+'). Hãy kiểm chứng, không bịa thêm nguồn:']
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
            api=client()
            params={'model':model,'messages':msgs,'stream':True,'temperature':float(os.getenv('AI_TEMPERATURE','0.7')),'max_tokens':int(os.getenv('AI_MAX_TOKENS','4096'))}
            try:
                stream=api.chat.completions.create(**params)
            except Exception as first_error:
                detail=str(first_error).lower(); changed=False
                if 'temperature' in detail and any(w in detail for w in ('unsupported','not support','does not support','unknown parameter')):
                    params.pop('temperature',None);changed=True
                if 'max_tokens' in detail and any(w in detail for w in ('unsupported','not support','unknown parameter','use max_completion_tokens')):
                    params['max_completion_tokens']=params.pop('max_tokens',4096);changed=True
                if not changed: raise
                stream=api.chat.completions.create(**params)
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
    return Response(generate(),mimetype='text/event-stream',headers={'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no','Connection':'keep-alive'})
@app.errorhandler(413)
def too_large(_):return jsonify(error=f"Tệp vượt giới hạn {app.config['MAX_CONTENT_LENGTH']//(1024*1024)} MB. Chỉnh MAX_UPLOAD_MB trên Render nếu cần."),413
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
