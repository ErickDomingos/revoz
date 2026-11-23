"""EXEMPLO do contrato que o item 7 precisa cumprir.

Para integrar: criar um arquivo chamado rvc_service.py (sem _EXEMPLO) nesta pasta,
com uma função convert_voice com ESTA assinatura. O main.py detecta o arquivo sozinho.
"""


def convert_voice(input_audio_path: str, output_audio_path: str,
                  pth_path: str, index_path: str) -> None:
    """
    input_audio_path : áudio genérico gerado pelo gTTS (.mp3)
    output_audio_path: onde gravar o áudio convertido (.wav) -> o main.py devolve esse arquivo
    pth_path         : modelo da voz (já resolvido pelo voice_registry)
    index_path       : .index da voz, ou '' se não existir
    Deve gravar o arquivo em output_audio_path e levantar exceção se falhar.

    Dica: se o RVC precisar do ambiente dele (versões travadas de fastapi/torch),
    chamar o RVC como processo separado com o python do venv do RVC:
        subprocess.run([r"C:\\...\\Retrieval-based-Voice-Conversion-WebUI\\.venv\\Scripts\\python.exe", ...], check=True)
    """
    raise NotImplementedError("trocar pela chamada real do RVC")
