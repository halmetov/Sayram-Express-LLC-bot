from django.contrib import admin
from .models import Category, Question, UserQuestion,TeleUser

admin.site.site_header = "Sayram Express LLC"
admin.site.site_title = "Sayram Express LLC Admin Page"

@admin.register(TeleUser)
class TeleUserAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'nickname', 'truck_number', 'telegram_id')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'responsible_chat', 'responsible_topic_id', 'id')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'id')

@admin.register(UserQuestion)
class UserQuestionAdmin(admin.ModelAdmin):
    list_display = ('username','group', 'date', 'category', 'question','responsible_id', 'id')