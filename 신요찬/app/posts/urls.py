from django.urls import path

from . import views

app_name = "posts"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("new/", views.post_create, name="create"),
    path("shared/", views.shared_list, name="shared"),
    path("<int:pk>/", views.post_detail, name="detail"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
    path("<int:pk>/shares/", views.post_shares, name="shares"),
    path("<int:pk>/shares/<int:share_id>/revoke/", views.share_revoke, name="share_revoke"),
    path("<int:pk>/attachments/", views.attachment_upload, name="attachment_upload"),
    path(
        "<int:pk>/attachments/<int:attachment_id>/download/",
        views.attachment_download,
        name="attachment_download",
    ),
    path("<int:pk>/attachments/<int:attachment_id>/delete/", views.attachment_delete, name="attachment_delete"),
]
