# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
# 确保从我们创建的 attendance_logic.py 文件导入
from attendance_logic import get_courses, run_brute_force_sign_in, run_single_sign_in

app = Flask(__name__)
# 重要提示：为生产环境设置一个强密钥！
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-replace-this!')

SESSION_COURSES_KEY = 'current_courses'

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        jsessionid_input = request.form.get('jsessionid', '').strip()
        if not jsessionid_input:
            flash('JSESSIONID 不能为空。', 'error')
            # 重定向回 GET 请求，显示登录页和 flash 消息
            return redirect(url_for('login'))

        # --- 新增：在登录时立即尝试验证 JSESSIONID ---
        print(f"尝试使用 JSESSIONID 验证登录: {jsessionid_input[:10]}...") # 打印部分ID用于调试
        validation_result = get_courses(jsessionid_input)

        if validation_result['success']:
            # 验证成功 (即使没有课程，只要 API 调用成功且 cookie 有效)
            session['jsessionid'] = jsessionid_input
            # 缓存获取到的课程数据
            session[SESSION_COURSES_KEY] = validation_result.get('courses', [])
            flash('登录成功！', 'success') # 更新成功消息
            if not validation_result.get('courses'):
                flash('今天似乎没有课程安排。', 'info') # 如果成功但没课程，也提示一下

            return redirect(url_for('dashboard'))
        else:
            # 验证失败
            error_message = validation_result.get('error', '未知错误')
            print(f"JSESSIONID 验证失败: {error_message}") # 打印错误日志

            # 根据错误类型显示不同的 flash 消息
            # 修改这里的判断条件以匹配 get_courses 中返回的特定错误消息
            if "无效的 JSESSIONID" in error_message or "请登录" in error_message or "Invalid JSESSIONID" in error_message:
                 flash('登录失败：JSESSIONID 无效或已过期，请检查后重新输入。', 'error')
            elif "网络请求失败" in error_message:
                 flash(f'登录验证失败：无法连接到服务器。请检查网络连接。({error_message})', 'error')
            else:
                 flash(f'登录验证失败：{error_message}', 'error')

            # 不设置 session，不重定向，停留在登录页显示错误
            # 需要确保 login.html 能正确显示 flash 消息
            return render_template('login.html')

    # --- GET 请求部分 ---
    # 如果 session 中已有有效的 jsessionid，直接重定向到 dashboard
    if 'jsessionid' in session:
        # （可选）可以加一步验证，确保 session 中的 ID 仍然有效，但这会增加每次访问的开销
        # 如果不加验证，用户可能会看到 dashboard，然后在刷新或操作时才发现 cookie 过期
        return redirect(url_for('dashboard'))

    # 显示登录页面 (处理 GET 请求，或者 POST 验证失败后重新渲染)
    return render_template('login.html')

# --- dashboard, refresh_courses, signin, logout 函数保持不变 ---
# (请确保这些函数在 app.py 文件中仍然存在且内容正确)
@app.route('/dashboard')
def dashboard():
    if 'jsessionid' not in session:
        flash('请先登录。', 'error')
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    courses_data = session.get(SESSION_COURSES_KEY)

    # 如果 session 中没有课程缓存 (例如，session 过期后重新打开，或者直接访问 dashboard)
    # 或者用户点击了刷新按钮（虽然刷新逻辑在 refresh_courses 中处理，但以防万一）
    # 则尝试重新获取课程
    if courses_data is None: # 使用 is None 检查缓存是否存在，空列表 [] 是有效缓存
        print("缓存未命中或需要刷新，正在从 API 获取课程...")
        result = get_courses(jsessionid_cookie)
        if result['success']:
            courses_data = result['courses']
            session[SESSION_COURSES_KEY] = courses_data # 更新缓存
            if not courses_data:
                 flash(result.get('message', '今天没有找到课程。'), 'info')
        else:
            flash(f"获取课程时出错: {result['error']}", 'error')
            if "无效的 JSESSIONID" in result.get('error', ''):
                 # 如果在这里发现 cookie 失效，登出用户
                 return redirect(url_for('logout'))
            courses_data = [] # 出错时显示空列表
            session.pop(SESSION_COURSES_KEY, None) # 清除可能无效的缓存

    # (此处省略了之前 dashboard 中用于处理无课程时 message 的逻辑，因为 flash 更常用)
    # 如果 courses_data 仍然是 None (例如获取失败且未被设置为空列表)，确保模板能处理
    if courses_data is None:
        courses_data = []

    return render_template('dashboard.html', courses=courses_data)


@app.route('/refresh')
def refresh_courses():
    if 'jsessionid' not in session:
        return redirect(url_for('login'))
    session.pop(SESSION_COURSES_KEY, None)
    flash('课程列表已刷新。', 'info') # 更新提示信息
    return redirect(url_for('dashboard'))


@app.route('/signin', methods=['POST'])
def signin():
    if 'jsessionid' not in session:
        flash('会话已过期。请重新登录。', 'error')
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    # 从 session 获取课程数据，确保后续操作基于这个数据
    courses = session.get(SESSION_COURSES_KEY)

    # 检查 courses 是否存在且不为 None
    if courses is None:
        flash('课程数据丢失，请尝试刷新页面。', 'error')
        return redirect(url_for('dashboard'))

    selected_course_ui_id = request.form.get('selected_course')
    action_type = request.form.get('action_type')

    if not selected_course_ui_id:
        flash('未选择课程。', 'error')
        return redirect(url_for('dashboard'))

    # 在 session 缓存的 courses 中查找选中的课程
    selected_course = next((c for c in courses if c.get('ui_id') == selected_course_ui_id), None)

    if not selected_course:
         flash('选择的课程无效或数据已过期，请刷新。', 'error')
         return redirect(url_for('dashboard'))

    course_plan_id = selected_course.get('coursePlanId')
    attendance_id = selected_course.get('attendanceId')
    course_name = selected_course.get('courseName', '未知课程')

    if not course_plan_id or not attendance_id:
        flash(f'无法为“{course_name}”签到。签到可能尚未开始 (缺少 Plan ID 或 Attendance ID)。请刷新。', 'error')
        return redirect(url_for('dashboard'))

    result = None
    print(f"收到签到请求 - 课程: {course_name}, 类型: {action_type}") # 添加日志

    try: # 包裹签到逻辑调用，捕获意外错误
        if action_type == 'brute_force':
            flash(f'开始为“{course_name}”进行暴力破解签到。这可能需要时间...', 'info')
            print(f"开始暴力破解 - PlanID: {course_plan_id}, AttID: {attendance_id}")
            result = run_brute_force_sign_in(jsessionid_cookie, course_plan_id, attendance_id)

        elif action_type == 'manual':
            manual_code = request.form.get('manual_code', '').strip()
            # 验证签到码格式
            try:
                code_int = int(manual_code)
                if not (0 <= code_int <= 9999):
                    raise ValueError("签到码必须在 0 到 9999 之间。")
                manual_code_formatted = f"{code_int:04d}" # 格式化为四位
            except ValueError:
                 flash('输入的签到码无效。必须是 0000 到 9999 之间的数字。', 'error')
                 return redirect(url_for('dashboard'))

            flash(f'尝试使用签到码 {manual_code_formatted} 为“{course_name}”签到...', 'info')
            print(f"开始手动签到 - PlanID: {course_plan_id}, AttID: {attendance_id}, Code: {manual_code_formatted}")
            result = run_single_sign_in(jsessionid_cookie, course_plan_id, attendance_id, manual_code_formatted)

        else:
            flash('选择了无效的操作。', 'error')
            return redirect(url_for('dashboard'))

    except Exception as e:
        # 捕获签到逻辑中的意外错误
        print(f"执行签到操作时发生意外错误: {e}")
        flash(f"执行签到操作时发生内部错误: {e}", 'error')
        return redirect(url_for('dashboard'))


    # 处理签到结果
    if result:
        print(f"签到操作完成 - 结果: {result}") # 添加日志
        if result['success']:
            flash(f"“{course_name}”签到成功: {result['message']}", 'success')
            # 成功后，可以选择性地清除课程缓存以强制下次刷新，或者保留缓存
            # session.pop(SESSION_COURSES_KEY, None)
        else:
            flash(f"“{course_name}”签到失败: {result['error']}", 'error')
            attempts = result.get('attempts')
            if attempts is not None:
                 flash(f"总尝试次数: {attempts}", 'info')
    else:
        # 如果 result 为 None (理论上不应发生，除非上面逻辑有误)
        flash("签到操作未返回有效结果。", 'warning')


    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.pop('jsessionid', None)
    session.pop(SESSION_COURSES_KEY, None)
    flash('您已成功登出。', 'success')
    return redirect(url_for('login'))

# --- Main execution ---
# ( Gunicorn in Docker runs this part, no need for __main__ block usually )