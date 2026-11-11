"""업로드 임시 파일 위치 (명세 3.4 "수신과 임시 저장").

Django 기본 처리기는 FILE_UPLOAD_TEMP_DIR(없으면 시스템 /tmp)에 임시 파일을 만든다.
여기서는 최종 저장 위치와 같은 파일시스템인 HAVEN_UPLOAD_DIR/.incoming에 만든다.
- 서버 프로세스가 쓸 수 있는 곳은 uploads 하나뿐이다(안민수 web-setup.sh의 ReadWritePaths).
- 폴더는 첫 업로드 때 만든다. settings에 고정하면 폴더가 없는 PC·CI에서 check가 실패한다.
- 임시 파일 이름에 사용자가 보낸 파일 이름을 쓰지 않는다.
- 업로드 경로에서는 파일 이름을 Django가 고쳤는지 기록해 view가 400으로 거부할 수 있게 한다.
- 요청이 끝나면 Django가 임시 파일을 닫고 지운다. 업로드 도중 끊기면 여기서 바로 지운다(UP-13).
  그래도 남은 파일(프로세스 강제 종료 등)은 cleanup_attachments가 지운다.
"""
import types

from django.core.files import temp as tempfile
from django.core.files.uploadedfile import TemporaryUploadedFile, UploadedFile
from django.core.files.uploadhandler import TemporaryFileUploadHandler
from django.http.multipartparser import MultiPartParser
from django.utils.datastructures import ImmutableList


class IncomingUploadedFile(TemporaryUploadedFile):
    def __init__(self, name, content_type, size, charset, content_type_extra=None):
        from .attachments import ensure_dirs, incoming_dir

        ensure_dirs()
        file = tempfile.NamedTemporaryFile(prefix="upload-", suffix=".tmp", dir=str(incoming_dir()))
        UploadedFile.__init__(self, file, name, content_type, size, charset, content_type_extra)


class IncomingFileUploadHandler(TemporaryFileUploadHandler):
    def new_file(self, *args, **kwargs):
        super(TemporaryFileUploadHandler, self).new_file(*args, **kwargs)
        self.file = IncomingUploadedFile(self.file_name, self.content_type, 0, self.charset, self.content_type_extra)


class StrictNameMultiPartParser(MultiPartParser):
    """Django는 파일 이름의 경로·제어문자를 조용히 지우고 넘긴다.

    명세 3.4는 그런 이름을 400으로 거부하라고 하므로, 지우기 전과 후가 다르면 표시만 해 둔다.
    (경로 구분자 / \\, NUL·CR·LF 등 출력 불가 문자, ".", "..", HTML 엔티티)
    255자를 넘는 이름도 Django가 뒤에서 조용히 자르므로 같은 방식으로 표시한다.
    """

    unsafe_name = False

    def sanitize_file_name(self, file_name):
        cleaned = super().sanitize_file_name(file_name)
        if cleaned != file_name or len(file_name) > 255:
            self.unsafe_name = True
        return cleaned


def _strict_parse_file_upload(request, META, post_data):
    """HttpRequest.parse_file_upload와 같고 파서만 바꾼다. 결과를 request.unsafe_upload_name에 남긴다."""
    request.upload_handlers = ImmutableList(
        request.upload_handlers,
        warning="You cannot alter upload handlers after the upload has been processed.",
    )
    parser = StrictNameMultiPartParser(META, post_data, request.upload_handlers, request.encoding)
    try:
        result = parser.parse()
    except Exception:
        # 업로드 도중 연결이 끊기는 등 파싱이 실패하면, Django는 다 받은 파일만 닫고
        # 받는 중이던 임시 파일은 열린 채로 둔다(메모리 정리 때까지 .incoming에 남음).
        # 여기서 바로 닫고 지운다(명세 UP-13). 그래도 남는 것은 cleanup_attachments가 지운다.
        for handler in request.upload_handlers:
            handler.upload_interrupted()
        raise
    request.unsafe_upload_name = parser.unsafe_name
    return result


def use_strict_name_parser(request):
    """업로드 경로에서 CSRF 검사가 multipart를 파싱하기 전에 호출한다(미들웨어)."""
    request.unsafe_upload_name = False
    request.parse_file_upload = types.MethodType(_strict_parse_file_upload, request)
