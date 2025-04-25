# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
# 确保从我们创建的 attendance_logic.py 文件导入
from attendance_logic import get_courses, run_brute_force_sign_in, run_single_sign_in

app = Flask(__name__)
# 重要提示：为生产环境设置一个强密钥！
# 可以使用以下命令生成：python -c 'import os; print(os.urandom(24))'
# 对于 Docker，最好通过环境变量设置。
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-replace-this!')

# 临时将会话中获取的课程存储起来
# 注意：如果课程非常多，会话大小限制可能成为问题，但对于此规模来说还好。
SESSION_COURSES_KEY = 'current_courses'

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        jsessionid = request.form.get('jsessionid', '').strip()
        if not jsessionid:
            flash('JSESSIONID 不能为空。', 'error') # 改为中文
            return redirect(url_for('login'))

        # 将 cookie 存储在 session 中
        session['jsessionid'] = jsessionid
        session.pop(SESSION_COURSES_KEY, None) # 新登录时清除旧课程
        flash('登录成功。正在获取课程...', 'success') # 改为中文
        # 重定向到 dashboard，它将获取课程
        return redirect(url_for('dashboard'))

    # 如果已登录，重定向到 dashboard
    if 'jsessionid' in session:
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'jsessionid' not in session:
        flash('请先登录。', 'error') # 改为中文
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    # 首先尝试从 session 缓存中获取课程
    courses_data = session.get(SESSION_COURSES_KEY)

    if not courses_data: # 如果未缓存，则获取它们
        print("正在从 API 获取课程...") # 改为中文
        result = get_courses(jsessionid_cookie)
        if result['success']:
            courses_data = result['courses']
            session[SESSION_COURSES_KEY] = courses_data # 缓存结果
            if not courses_data:
                 flash(result.get('message', '今天没有找到课程。'), 'info') # 改为中文
        else:
            flash(f"获取课程时出错: {result['error']}", 'error') # 改为中文
            # 如果 cookie 无效，则将用户登出
            if "无效的 JSESSIONID" in result.get('error', ''): # 改为中文
                 return redirect(url_for('logout'))
            courses_data = [] # 确保 dashboard 在没有课程的情况下呈现
            session.pop(SESSION_COURSES_KEY, None) # 清除无效缓存

    # 如果没有课程数据，则传递 flash 消息给模板
    message_to_render = None
    if not courses_data and get_flashed_messages():
         # 如果没有课程且有 flash 消息，让模板处理 flash
         pass
    elif not courses_data:
        # 如果没有课程且没有 flash 消息（可能是第一次加载或刷新后）
        message_to_render = "目前没有可显示的课程，或需要刷新。" # 添加一个默认消息

    return render_template('dashboard.html', courses=courses_data, message=message_to_render)

@app.route('/refresh')
def refresh_courses():
    if 'jsessionid' not in session:
        return redirect(url_for('login'))

    # 清除 session 中的课程缓存
    session.pop(SESSION_COURSES_KEY, None)
    flash('课程列表缓存已清除。正在刷新...', 'info') # 改为中文
    return redirect(url_for('dashboard'))


@app.route('/signin', methods=['POST'])
def signin():
    if 'jsessionid' not in session:
        flash('会话已过期。请重新登录。', 'error') # 改为中文
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    courses = session.get(SESSION_COURSES_KEY)

    if not courses:
        flash('Session 中缺少课程数据。请刷新仪表盘。', 'error') # 改为中文
        return redirect(url_for('dashboard'))

    selected_course_ui_id = request.form.get('selected_course')
    action_type = request.form.get('action_type')

    if not selected_course_ui_id:
        flash('未选择课程。', 'error') # 改为中文
        return redirect(url_for('dashboard'))

    # 使用隐藏字段或通过搜索课程列表找到所选课程的详细信息
    # 使用隐藏字段在 session 数据过时的情况下不太健壮，但在这里更简单。
    # course_plan_id = request.form.get(f'{selected_course_ui_id}_plan_id')
    # attendance_id = request.form.get(f'{selected_course_ui_id}_att_id')

    # 备选方案：在 session 数据中查找课程（更健壮）
    selected_course = next((c for c in courses if c.get('ui_id') == selected_course_ui_id), None)

    if not selected_course:
         flash('在 Session 数据中找不到所选课程。请刷新。', 'error') # 改为中文
         return redirect(url_for('dashboard'))

    course_plan_id = selected_course.get('coursePlanId')
    attendance_id = selected_course.get('attendanceId')
    course_name = selected_course.get('courseName', '未知课程') # 改为中文


    if not course_plan_id or not attendance_id:
        flash(f'无法为“{course_name}”签到。签到可能尚未开始（缺少 Plan ID 或 Attendance ID）。请刷新。', 'error') # 改为中文
        return redirect(url_for('dashboard'))

    result = None
    if action_type == 'brute_force':
        flash(f'开始为“{course_name}”进行暴力破解签到。这可能需要时间...', 'info') # 改为中文
        print(f"开始暴力破解 - 课程: {course_name}, PlanID: {course_plan_id}, AttID: {attendance_id}") # 改为中文
        # 运行调用异步代码的同步包装器
        result = run_brute_force_sign_in(jsessionid_cookie, course_plan_id, attendance_id)

    elif action_type == 'manual':
        manual_code = request.form.get('manual_code', '').strip()
        if not manual_code.isdigit() or not (0 <= int(manual_code) <= 9999):
             flash('输入的手动签到码无效。必须是 0000-9999。', 'error') # 改为中文
             return redirect(url_for('dashboard'))

        # 格式化为4位，前面补零
        manual_code_formatted = f"{int(manual_code):04d}"
        flash(f'尝试使用签到码 {manual_code_formatted} 为“{course_name}”签到...', 'info') # 改为中文
        print(f"开始手动签到 - 课程: {course_name}, PlanID: {course_plan_id}, AttID: {attendance_id}, 签到码: {manual_code_formatted}") # 改为中文
        result = run_single_sign_in(jsessionid_cookie, course_plan_id, attendance_id, manual_code_formatted) # 传递格式化后的

    else:
        flash('选择了无效的操作。', 'error') # 改为中文
        return redirect(url_for('dashboard'))

    # 处理结果
    if result:
        if result['success']:
            flash(f"“{course_name}”成功: {result['message']}", 'success') # 改为中文
            # 可选：如果需要，在成功签到后清除课程缓存
            # session.pop(SESSION_COURSES_KEY, None)
        else:
            flash(f"“{course_name}”失败: {result['error']}", 'error') # 改为中文
            attempts = result.get('attempts')
            if attempts is not None:
                 flash(f"总尝试次数: {attempts}", 'info') # 改为中文


    # 重定向回 dashboard 以显示状态
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.pop('jsessionid', None)
    session.pop(SESSION_COURSES_KEY, None)
    flash('您已成功登出。', 'success') # 改为中文
    return redirect(url_for('login'))

# --- 主执行 ---
# 在生产环境中使用 Gunicorn 或其他 WSGI 服务器（在 Dockerfile/docker-compose 中定义）
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0') # 用于本地无 Docker 测试