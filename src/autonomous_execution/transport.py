"""Local-only adapter with resource error classification for long-running jobs.

The historical transport remains byte-for-byte unchanged. No redirect, proxy,
cloud fallback, download, streaming, tools or implicit inference retries.
"""
import http.client
import json
import socket
from layer4_evaluation.indicators.ollama_provider import OllamaClient, OllamaError, strict_json, server_error


def classify(status,message):
    text=message.lower()
    if any(fragment in text for fragment in ('requires more system memory','insufficient memory',
            'insufficient vram','failed to allocate','failed to load model due to memory')):
        return OllamaError('OUT_OF_MEMORY','Ollama rechazo la reserva de memoria; no aumentar contexto')
    if status in (429,503):
        return OllamaError('SERVER_BUSY','Ollama local ocupado; reintento acotado por politica')
    return server_error(status,message)


class AdaptiveClient(OllamaClient):
    def request(self,method,path,payload=None):
        if (method,path) not in {('GET','/api/version'),('GET','/api/tags'),('POST','/api/show'),('POST','/api/chat')}:
            raise ValueError('Operacion local no autorizada')
        host='127.0.0.1' if self.url.hostname=='localhost' else self.url.hostname
        connection=http.client.HTTPConnection(host,self.url.port or 11434,timeout=self.settings['timeout_seconds'])
        try:
            body=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
            connection.request(method,path,body=body,headers={'Content-Type':'application/json'})
            response=connection.getresponse()
            data=response.read(32*1024*1024+1)
            if len(data)>32*1024*1024:
                raise OllamaError('INVALID_RESPONSE','Respuesta local excede limite de memoria permitido')
            try:
                value=strict_json(data.decode('utf-8'))
            except (ValueError,UnicodeError):
                raise OllamaError('INVALID_RESPONSE','Servidor local no devolvio JSON valido') from None
            if response.status!=200 or not isinstance(value,dict) or value.get('error'):
                raise classify(response.status,str(value.get('error','')) if isinstance(value,dict) else '')
            return value
        except (TimeoutError,socket.timeout):
            raise OllamaError('TIMEOUT','Timeout local; conservar claim sin repetir resultado incierto') from None
        except (OSError,http.client.HTTPException):
            raise OllamaError('SERVER_UNAVAILABLE','Servidor local no disponible') from None
        finally:
            connection.close()
