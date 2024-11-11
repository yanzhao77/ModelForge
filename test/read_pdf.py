import os

os.environ['HTTP_PROXY'] = '127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = '127.0.0.1:7890'

from docling.document_converter import DocumentConverter

source = "C:\\Users\\Administrator.NYANZHAO\\OneDrive\\ebook\\大型机\\IBM大型机汇编语言.pdf"  # PDF path or URL
converter = DocumentConverter()
result = converter.convert(source)

print(result.render_as_markdown())  # 输出Markdown格式
print(result.render_as_doctags())  # 输出Doc Tags格式