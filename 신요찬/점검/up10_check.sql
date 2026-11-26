-- UP-10 복원본 확인 (읽기만 함). db-1에서 root로 (파일은 표준 입력으로 넘긴다. postgres 계정은 /root를 못 읽음):
--   rm -f /tmp/up10_attach.sha256
--   runuser -u postgres -- psql -X -d haven_restore_check -v ON_ERROR_STOP=1 < /root/up10/up10_check.sql
-- 결과는 t/f와 개수, 시험 계정 이름만 나온다. 글 내용·파일 이름은 나오지 않는다.
-- 시험 글은 "주인 up10_a + 제목 UP10-restore-check"로만 찾는다(다른 사람이 같은 제목을 써도 섞이지 않게).

\encoding UTF8

\pset footer off
\echo '== 1. 시험 글 (기대: 1)'
SELECT count(*) AS up10_posts
  FROM posts_post p JOIN auth_user o ON o.id = p.owner_id
 WHERE p.title = 'UP10-restore-check' AND p.status = 'ACTIVE' AND o.username = 'up10_a';

\echo '== 2. 계정 상태와 읽기 권한 (기대: 4줄, 모두 active t / can_read는 a t, b t, c f, d f)'
-- can_read는 앱과 같은 조건이다: 로그인할 수 있는 계정(is_active)이고,
-- readable_posts(posts/permissions.py)처럼 글이 ACTIVE·주인이 활성이며 주인이거나 지금 공유 행이 있다.
SELECT u.username,
       u.is_active AS active,
       (u.is_active AND EXISTS (
         SELECT 1 FROM posts_post p JOIN auth_user o ON o.id = p.owner_id
          WHERE p.title = 'UP10-restore-check' AND o.username = 'up10_a'
            AND p.status = 'ACTIVE' AND o.is_active
            AND (p.owner_id = u.id
                 OR EXISTS (SELECT 1 FROM posts_postshare s WHERE s.post_id = p.id AND s.recipient_id = u.id))
       )) AS can_read
  FROM auth_user u
 WHERE u.username IN ('up10_a', 'up10_b', 'up10_c', 'up10_d')
 ORDER BY u.username;

\echo '== 3. 시험 글의 공유 행 (기대: up10_b 하나. 해제하면 행이 지워지므로 up10_d는 없어야 함)'
SELECT r.username AS recipient
  FROM posts_postshare s
  JOIN posts_post p ON p.id = s.post_id
  JOIN auth_user o ON o.id = p.owner_id
  JOIN auth_user r ON r.id = s.recipient_id
 WHERE p.title = 'UP10-restore-check' AND o.username = 'up10_a'
 ORDER BY r.username;

\echo '== 4. 시험 글의 정상 첨부 수 (기대: 2)'
SELECT count(*) AS up10_active_attachments
  FROM posts_attachment a
  JOIN posts_post p ON p.id = a.post_id
  JOIN auth_user o ON o.id = p.owner_id
 WHERE p.title = 'UP10-restore-check' AND o.username = 'up10_a' AND a.status = 'ACTIVE';

\echo '== 5. 전체 정상 첨부 수와 대조 목록 (web-1에서 sha256sum -c로 파일과 맞춤)'
SELECT count(*) AS all_active_attachments,
       sum(size_bytes) AS all_active_bytes
  FROM posts_attachment WHERE status = 'ACTIVE';
\copy (SELECT sha256 || '  ' || storage_key FROM posts_attachment WHERE status = 'ACTIVE' ORDER BY id) TO '/tmp/up10_attach.sha256'
\echo '대조 목록을 /tmp/up10_attach.sha256 에 썼다 (sha256과 저장 키만, 파일 이름 없음)'
