#   -*- coding: utf-8 -*-
# @Author  : Weilong Zhu
# @Time    : 2022-05-06,15:27
# @File    : planner_utiles.py
"""
控制和规划要用的一些通用函数
"""
import math
import numpy as np
import carla
import cvxopt


def Vector_fun(loc_1: carla.Location, loc_2: carla.Location):
    """
    计算从loc_1指向loc_2的单位向量
    :param loc_1: carla.Location类型
    :param loc_2: carla.Location类型
    :return: list 类型【v_x, v_y, v_z】
    """

    delt_x = loc_2.x - loc_1.x
    delt_y = loc_2.y - loc_1.y
    delt_z = loc_2.z - loc_1.z
    norm = np.linalg.norm([delt_x, delt_y, delt_z]) + np.finfo(float).eps  # 后面一项不让norm为零
    return np.round([delt_x / norm, delt_y / norm, delt_z / norm], 4)  # 保留4位小数


def waypoint_list_2_target_path(pathway):
    """
    将由路点构成的路径转化为（x, y, theta, k）的形式
    :param pathway: 【waypoint0, waypoint1, ...】
    :return: [(x0, y0, theta0, k0), ...]
    """
    target_path = []
    w = None  # type: carla.Waypoint
    xy_list_ori = []
    for w in pathway:
        x = w[0].transform.location.x
        y = w[0].transform.location.y
        xy_list_ori.append((x, y))
    theta_list, kappa_list = cal_heading_kappa(xy_list_ori)
    # self._target_path = smooth_reference_line(xy_list_ori)  # 对生成的原始轨迹进行平滑,这里只是做了个实验
    for i in range(len(theta_list)):
        target_path.append((xy_list_ori[i][0], xy_list_ori[i][1], theta_list[i], kappa_list[i]))
    return target_path


def find_match_points(xy_list: list, frenet_path_node_list: list, is_first_run: bool, pre_match_index: int):
    """
    计算笛卡尔坐标系（直角坐标系）下的位置(x,y)，在frenet（自然坐标系）路径上的匹配点索引和投影点位置信息
    即输入若干个坐标，返回他们的匹配点索引值和在frenet曲线上的投影点
    注：老王在这里考虑的比较多，考虑了后面有多个点需要投影的情况，在平滑阶段，每次是只有一个需要投影的
    由于匹配点是frenet曲线（离散的点构成）中已知的点，所以返回索引即可，投影点一般不在frenet曲线上
    :param pre_match_index: 上个匹配点的索引
    :param is_first_run: 标志是否是第一次运行匹配点算法，如果是就从起点搜索，如果不是就从上个周期的匹配点搜索
    :param xy_list: 笛卡尔坐标西下一系列的点的坐标xy_list = [(x0, y0), (x1, y1), ...)
    :param frenet_path_node_list: frenet坐标系下路径点信息,指的是全局路径点
           frenet_path_node_list = [(x0, y0, heading0, kappa0), ...],（x, y, 切线与x轴夹角， 曲率）
    :return:
    match_point_index_list 匹配点的索引
    project_node_list 投影点的位置信息， project_node_list = [(x_p0, y_p0, heading_p0, kappa_p0), ...]
    """

    i = -1  # 提前定义一个变量用于遍历曲线上的点
    input_xy_length = len(xy_list)
    frenet_path_length = len(frenet_path_node_list)

    match_point_index_list = np.zeros(input_xy_length, dtype="int32")
    project_node_list = []  # 最终长度和input_xy_length应该相同

    if is_first_run is True:
        for index_xy in range(pre_match_index, input_xy_length):  # 为每一个点寻找匹配点
            x, y = xy_list[index_xy]
            start_index = 0
            # 用increase_count记录distance连续增大的次数，避免多个局部最小值的干扰
            increase_count = 0
            min_distance = float("inf")
            # 确定匹配点
            for i in range(start_index, frenet_path_length):
                frenet_node_x, frenet_node_y, _, _ = frenet_path_node_list[i]
                # 计算（x,y) 与 （frenet_node_x, frenet_node_y） 之间的距离
                distance = math.sqrt((frenet_node_x - x) ** 2 + (frenet_node_y - y) ** 2)
                if distance < min_distance:
                    min_distance = distance  # 保留最小值
                    match_point_index_list[index_xy] = i
                    increase_count = 0
                else:
                    increase_count += 1
                    if increase_count >= 50:  # 向后50个点还没找到的话，说明当前最小值点及时最优的
                        # 第一次运行阈值较大，是为了保证起始点匹配的精确性
                        break
            # 通过匹配点确定投影点
            """
            (x, y)'表示向量转置
            d_v是匹配点（x_m, y_m）指向待投影点（x,y）的向量（x-x_m, y-y_m）
            tou_v是匹配点的单位切向量(cos(theta_m), sin(theta_m))'
            (x_r, y_r)' 约等于 (x_m, y_m)' + (d_v . tou_v)*tou_v
            k_r 约等于 k_m， 投影点曲率
            theta_r 约等于 theta_m + k_m*(d_v . tou_v)， 投影点切线与坐标轴夹角
            具体原理看笔记分析
            """
            match_point_index = match_point_index_list[0]
            x_m, y_m, theta_m, k_m = frenet_path_node_list[match_point_index]
            d_v = np.array([x - x_m, y - y_m])
            tou_v = np.array([np.cos(theta_m), np.sin(theta_m)])
            ds = np.dot(d_v, tou_v)
            r_m_v = np.array([x_m, y_m])
            # 根据公式计算投影点的位置信息
            x_r, y_r = r_m_v + ds * tou_v  # 计算投影点坐标
            theta_r = theta_m + k_m * ds  # 计算投影点在frenet曲线上切线与X轴的夹角
            k_r = k_m  # 投影点在frenet曲线处的曲率
            # 将结果打包放入缓存区
            project_node_list.append((x_r, y_r, theta_r, k_r))

    else:
        for index_xy in range(input_xy_length):  # 为每一个点寻找匹配点
            x, y = xy_list[index_xy]
            """
            这里有一个疑问，如果在某个周期内做执行匹配算法时有多个目标点对应多个匹配点，那下一个周期要使用的上个周期的匹配点应该选哪一个比较合适
            这里直接选取的时pre_match_index[index_xy]，index_xy还是新的
            """
            start_index = pre_match_index
            # 用increase_count记录distance连续增大的次数，避免多个局部最小值的干扰
            increase_count = 0
            # 上个周期匹配点坐标
            pre_match_point_xy = [frenet_path_node_list[start_index][0], frenet_path_node_list[start_index][1]]
            pre_match_point_theta_m = frenet_path_node_list[start_index][2]
            # 上个匹配点在曲线上的切向向量
            pre_match_point_direction = np.array([np.cos(pre_match_point_theta_m), np.sin(pre_match_point_theta_m)])
            # 计算上个匹配点指向当前(x, y）的向量
            pre_match_to_xy_v = np.array([x - pre_match_point_xy[0], y - pre_match_point_xy[1]])
            # 计算pre_match_to_xy_v在pre_match_point_direction上的投影，用于判断遍历方向
            flag = np.dot(pre_match_to_xy_v, pre_match_point_direction)  # 大于零正反向遍历，反之，反方向遍历

            min_distance = float("inf")
            if flag > 0:
                for i in range(start_index, frenet_path_length):
                    frenet_node_x, frenet_node_y, _, _ = frenet_path_node_list[i]
                    # 计算（x,y) 与 （frenet_node_x, frenet_node_y） 之间的距离
                    distance = math.sqrt((frenet_node_x - x) ** 2 + (frenet_node_y - y) ** 2)
                    if distance < min_distance:
                        min_distance = distance  # 保留最小值
                        match_point_index_list[index_xy] = i
                        increase_count = 0
                    else:
                        increase_count += 1
                        if increase_count >= 5:  # 为了加快速度，这里阈值为5，第一个周期是不同的，向后5个点还没找到的话，说明当前最小值点及时最优的
                            break
            else:
                for i in range(start_index, -1, -1):
                    frenet_node_x, frenet_node_y, _, _ = frenet_path_node_list[i]
                    # 计算（x,y) 与 （frenet_node_x, frenet_node_y） 之间的距离
                    distance = math.sqrt((frenet_node_x - x) ** 2 + (frenet_node_y - y) ** 2)
                    if distance < min_distance:
                        min_distance = distance  # 保留最小值
                        match_point_index_list[index_xy] = i
                        increase_count = 0
                    else:
                        increase_count += 1
                        if increase_count >= 5:
                            break
            # 通过匹配点确定投影点
            match_point_index = match_point_index_list[0]
            x_m, y_m, theta_m, k_m = frenet_path_node_list[match_point_index]
            d_v = np.array([x - x_m, y - y_m])
            tou_v = np.array([np.cos(theta_m), np.sin(theta_m)])
            ds = np.dot(d_v, tou_v)
            r_m_v = np.array([x_m, y_m])
            # 根据公式计算投影点的坐标信息
            x_r, y_r = r_m_v + ds * tou_v
            theta_r = theta_m + k_m * ds
            k_r = k_m
            # 将结果打包放入缓存区
            project_node_list.append((x_r, y_r, theta_r, k_r))

    return list(match_point_index_list), project_node_list


def cal_heading_kappa(frenet_path_xy_list: list):
    """
    计算frenet曲线上每个点的切向角theta（与直角坐标轴之间的角度）和曲率k
    :param frenet_path_xy_list: 包含frenet曲线上每一点的坐标[(x0,y0), (x1, y1), ...]
    :return: list类型， theta = [theta0, theta1,...], k = [k0, k1, k2, ...]
    原理:
    theta = arctan(d_y/d_x)
    kappa = d_theta / d_s
    d_s = (d_x^2 + d_y^2)^0.5
    采用中点欧拉法来计算每个点处的斜率,当前点前一个线段斜率和后一个线段斜率求平均值
    """
    dx_ = []
    dy_ = []
    for i in range(len(frenet_path_xy_list) - 1):
        dx_.append(frenet_path_xy_list[i + 1][0] - frenet_path_xy_list[i][0])
        dy_.append(frenet_path_xy_list[i + 1][1] - frenet_path_xy_list[i][1])
    # 计算theta,切线方向角
    # 由于n个点差分得到的只有n-1个差分结果，所以要在首尾添加重复单元来近似求每个节点的dx,dy
    dx_pre = [dx_[0]] + dx_  # 向前补dx_的第一位
    dx_aft = dx_ + [dx_[-1]]  # 向后补dx_的最后一位
    dx = (np.array(dx_pre) + np.array(dx_aft)) / 2

    dy_pre = [dy_[0]] + dy_
    dy_aft = dy_ + [dy_[-1]]
    dy = (np.array(dy_pre) + np.array(dy_aft)) / 2
    theta = np.arctan2(dy, dx)  # np.arctan2会将角度限制在（-pi, pi）之间
    # 计算曲率
    d_theta_ = np.diff(theta)  # 差分计算
    d_theta_pre = np.insert(d_theta_, 0, d_theta_[0])
    d_theta_aft = np.insert(d_theta_, -1, d_theta_[-1])
    d_theta = np.sin((d_theta_pre + d_theta_aft) / 2)  # 认为d_theta是个小量，用sin(d_theta)代替d_theta,避免多值性
    ds = np.sqrt(dx ** 2 + dy ** 2)
    k = d_theta / ds

    return list(theta), list(k)


def sampling(match_point_index: int, frenet_path_node_list: list, back_length=10, forward_length=50):
    """
    根据匹配点确定局部参考线，用于后平滑和局部规划使用
    :param match_point_index: 当前匹配点在frenet曲线（全局离散路径）中的索引
    :param frenet_path_node_list: frenet曲线
    :param back_length: 投影点向后采样点数
    :param forward_length: 投影点向前采样点数

    :return: list类型， local_frenet_path = [node0, node1, node2, ...], node0 = (x0, y0, heading0, kappa0)
    采样的规则是，在匹配点之前的30个点和匹配点之后的150个点,这个可以根据实际调整，做到精确和速度的平衡就好
    如果前向不够，则向后增加点；如果后向不够，则向前增加点。保持总长度为181，为了后面平滑算法统一处理
    """
    local_frenet_path = []
    back_length = 10
    forward_length = 50
    length_sum = back_length + forward_length
    if match_point_index < back_length:
        back_length = match_point_index
        forward_length = length_sum - back_length

    if (len(frenet_path_node_list) - match_point_index) - 1 < forward_length:
        forward_length = len(frenet_path_node_list) - match_point_index - 1
        back_length = length_sum - forward_length

    local_frenet_path = frenet_path_node_list[match_point_index - back_length: match_point_index] \
                        + frenet_path_node_list[match_point_index: match_point_index + forward_length + 1]

    return local_frenet_path


def smooth_reference_line(local_frenet_path_xy: list,
                          w_cost_smooth=0.4, w_cost_length=0.3, w_cost_ref=0.3,
                          x_thre=0.2, y_thre=0.2):
    """
    对原始参考线进行平滑处理,采用二次规划, 平滑后再计算theta和kappa
    :param local_frenet_path_xy: 可以是[(x_ref0, y_ref0), (x_ref1, y_ref1), ...]，
    也可以是[(x_ref0, y_ref0，theta0, kappa0), (x_ref1, y_ref1, theta1, kappa1), ...],
    二次规划只是对离散曲线进行平滑，索引索引的是元组的前两个元素x，y，规划后再计算theta和曲率
    :param w_cost_smooth: 平滑代价权重
    :param w_cost_length: 紧凑代价权重
    :param w_cost_ref: 几何相似代价权重
    三个权重的确定直接影响平滑的形状，这里值重要的超参数
    :param y_thre: x的波动阈值，阈值用于约束目标值不要和原始值相差太远
    :param x_thre: y的波动阈值
    :return: 优化后的坐标 local_path_xy_opt= [(x_opt0, y_opt0, theta_0, kappa_0), ...]
    使用二次规划进行平滑处理，具体理论看笔记
    min(0.5*x'.H.x + f'x)
    x_ref - x_thre < x < x_ref + x_thre
    y_ref - y_thre < y < y_ref + y_thre
    原理：
    H1 = w_cost_smooth*(A1'.A1) + w_cost_length*(A2'.A2) + w_cost_ref*(A3'.A3)
    H = 2*H1
    f = -2*w_cost_ref*[x_ref0,y_ref0,x_ref1,y_ref1,...]'
    0.5*x'.H.x + f'x = 0.5*x'.H.x + f'x
    A1 = [1 0 -2 0 1 0
          0 1 0 -2 0 1
              1 0 -2 0 1 0
              0 1 0 -2 0 1
                  .......
                  .......]
    A2 = [1 0 -1 0
          0 1 0 -1
              1 0 -1 0
              0 1 0 -1
                  .....
                  .....]
    A3 是单位矩阵
    设置求解矩阵的规模，每次的优化规模是181个点，每个点有两个坐标
    """
    n = len(local_frenet_path_xy)  # 该模块是对参考线输出进行处理的时候就是处理181个点
    x_ref = np.zeros(shape=(2 * n, 1))  # 【x_ref0, y_ref0, x_ref1, y_ref1, ...]' 输入坐标构成的坐标矩阵， (2*n, 1)
    lb = np.zeros(shape=(2 * n, 1))
    ub = np.zeros(shape=(2 * n, 1))
    for i in range(n):
        x_ref[2 * i] = local_frenet_path_xy[i][0]
        x_ref[2 * i + 1] = local_frenet_path_xy[i][1]
        # 确定上下边界
        lb[2 * i] = local_frenet_path_xy[i][0] - x_thre
        lb[2 * i + 1] = local_frenet_path_xy[i][1] - y_thre
        ub[2 * i] = local_frenet_path_xy[i][0] + x_thre
        ub[2 * i + 1] = local_frenet_path_xy[i][1] + y_thre

    A1 = np.zeros(shape=(2 * n - 4, 2 * n))
    for i in range(n - 2):
        A1[2 * i][2 * i + 0] = 1
        # A1[2 * i][2 * i + 1] = 0
        A1[2 * i][2 * i + 2] = -2
        # A1[2 * i][2 * i + 3] = 0
        A1[2 * i][2 * i + 4] = 1
        # A1[2 * i][2 * i + 5] = 0

        # A1[2 * i + 1][2 * i + 0] = 0
        A1[2 * i + 1][2 * i + 1] = 1
        # A1[2 * i + 1][2 * i + 2] = 0
        A1[2 * i + 1][2 * i + 3] = -2
        # A1[2 * i + 1][2 * i + 4] = 0
        A1[2 * i + 1][2 * i + 5] = 1

    A2 = np.zeros(shape=(2 * n - 2, 2 * n))
    for i in range(n - 1):
        A2[2 * i][2 * i + 0] = 1
        # A2[2 * i][2 * i + 1] = 0
        A2[2 * i][2 * i + 2] = -1
        # A2[2 * i][2 * i + 3] = 0

        # A2[2 * i + 1][2 * i + 0] = 0
        A2[2 * i + 1][2 * i + 1] = 1
        # A2[2 * i + 1][2 * i + 2] = 0
        A2[2 * i + 1][2 * i + 3] = -1

    A3 = np.identity(2 * n)
    H = 2 * (w_cost_smooth * np.dot(A1.transpose(), A1) +
             w_cost_length * np.dot(A2.transpose(), A2) +
             w_cost_ref * A3)

    f = -2 * w_cost_ref * x_ref
    # 将约束转化为矩阵形式
    G = np.concatenate((np.identity(2 * n), -np.identity(2 * n)))  # （4n, 2n）
    h = np.concatenate((ub, -lb))  # (4n, 1)
    cvxopt.solvers.options['show_progress'] = False  # 程序没有问题之后不再输出中间过程
    # 计算时要将输入转化为cvxopt.matrix
    # 该方法返回值是一个字典类型，包含了很多的参数，其中x关键字对应的是优化后的解
    res = cvxopt.solvers.qp(cvxopt.matrix(H), cvxopt.matrix(f), G=cvxopt.matrix(G), h=cvxopt.matrix(h))
    local_path_xy_opt = []
    for i in range(0, len(res['x']), 2):
        local_path_xy_opt.append((res['x'][i], res['x'][i + 1]))
    theta_list, k_list = cal_heading_kappa(local_path_xy_opt)
    x_y_theta_kappa_list = []
    for i in range(len(local_path_xy_opt)):
        x_y_theta_kappa_list.append(local_path_xy_opt[i] + (theta_list[i], k_list[i]))
    return x_y_theta_kappa_list


def match_projection_points(xy_list: list, frenet_path_node_list: list):
    """
    计算笛卡尔坐标系（直角坐标系）下的位置(x,y)，在参考线上的匹配点索引和投影点位置信息
    即输入若干个坐标，返回他们的匹配点索引值和在frenet曲线上的投影点
    由于匹配点是frenet曲线（离散的点构成）中已知的点，所以返回索引即可，投影点一般不在frenet曲线上
    :param xy_list: 笛卡尔坐标西下一系列的点的坐标xy_list = [(x0, y0), (x1, y1), ...)
    :param frenet_path_node_list: frenet坐标系下路径点信息,指的是全局路径点
           frenet_path_node_list = [(x0, y0, heading0, kappa0), ...],（x, y, 切线与x轴夹角， 曲率）
    :return:
    match_point_index_list 匹配点的索引
    project_node_list 投影点的位置信息， project_node_list = [(x_p0, y_p0, heading_p0, kappa_p0), ...]
    """

    input_xy_length = len(xy_list)
    frenet_path_length = len(frenet_path_node_list)

    match_point_index_list = np.zeros(input_xy_length, dtype="int32")
    project_node_list = []  # 最终长度和input_xy_length应该相同

    for index_xy in range(input_xy_length):  # 为每一个点寻找匹配点
        x, y = xy_list[index_xy]
        start_index = 0
        # 用increase_count记录distance连续增大的次数，避免多个局部最小值的干扰
        increase_count = 0
        min_distance = float("inf")
        # 确定匹配点
        for i in range(start_index, frenet_path_length):
            frenet_node_x, frenet_node_y, _, _ = frenet_path_node_list[i]
            # 计算（x,y) 与 （frenet_node_x, frenet_node_y） 之间的距离
            distance = math.sqrt((frenet_node_x - x) ** 2 + (frenet_node_y - y) ** 2)
            if distance < min_distance:
                min_distance = distance  # 保留最小值
                match_point_index_list[index_xy] = i
                increase_count = 0
            else:
                increase_count += 1
                if increase_count >= 50:  # 向后50个点还没找到的话，说明当前最小值点及时最优的
                    # 第一次运行阈值较大，是为了保证起始点匹配的精确性
                    break
        # 通过匹配点确定投影点
        """
        (x, y)'表示向量转置
        d_v是匹配点（x_m, y_m）指向待投影点（x,y）的向量（x-x_m, y-y_m）
        tou_v是匹配点的单位切向量(cos(theta_m), sin(theta_m))'
        (x_r, y_r)' 约等于 (x_m, y_m)' + (d_v . tou_v)*tou_v
        k_r 约等于 k_m， 投影点曲率
        theta_r 约等于 theta_m + k_m*(d_v . tou_v)， 投影点切线与坐标轴夹角
        具体原理看笔记分析
        """
        match_point_index = match_point_index_list[0]
        x_m, y_m, theta_m, k_m = frenet_path_node_list[match_point_index]
        d_v = np.array([x - x_m, y - y_m])
        tou_v = np.array([np.cos(theta_m), np.sin(theta_m)])
        ds = np.dot(d_v, tou_v)
        r_m_v = np.array([x_m, y_m])
        # 根据公式计算投影点的位置信息
        x_r, y_r = r_m_v + ds * tou_v  # 计算投影点坐标
        theta_r = theta_m + k_m * ds  # 计算投影点在frenet曲线上切线与X轴的夹角
        k_r = k_m  # 投影点在frenet曲线处的曲率
        # 将结果打包放入缓存区
        project_node_list.append((x_r, y_r, theta_r, k_r))

    return list(match_point_index_list), project_node_list


def cal_projection_s_fun(local_path_opt: list, match_index_list: list, xy_list: list, s_map: list):
    """已验证
    计算若干点的投影对应的s,
    :param local_path_opt: 优化后的参考线[(x, y, theta, kappa), ...]
    :param match_index_list: 给定点在参考线上点的索引列表
    :param xy_list:  给定点的坐标【（x, y）, ...】
    :param s_map: 参考s_map
    :return: 投影点对应的s
    """
    projection_s_list = []
    for i in range(len(match_index_list)):
        x, y, theta, kappa = local_path_opt[match_index_list[i]]
        d_v = np.array([xy_list[i][0] - x, xy_list[i][1] - y])  # 匹配点指向给定点的向量
        tou_v = np.array([math.cos(theta), math.sin(theta)])  # 切线方向单位向量
        projection_s_list.append(s_map[match_index_list[i]] + np.dot(d_v, tou_v))  # np.dot(d_v, tou_v)是有正负号的

    return projection_s_list


def cal_s_map_fun(local_path_opt: list, origin_xy: tuple):
    """
    计算参考线上每个节点与s的映射关系, 以车辆当前投影点为原点，不是以参考线的起点。, s就是弧长的，用折线来拟合的
    :param local_path_opt: 优化后的参考线[(x, y, theta, kappa), ...]
    :param origin_xy: 车辆当前的位置
    :return: s_map, list类型和输入的参考线长度相同
    """
    # 计算以车辆当前位置投影点为起点的s_map
    origin_match_index, _ = match_projection_points([origin_xy], local_path_opt)  # 通过
    # 车辆定位位置，计算其在参考线上的匹配点索引和投影点信息，match_projection_points处理的是一系列点的列表，
    # 因此输入要为列表形式，输出也是列表形式，但是里面只有一个元素，因此索引第一位就行了
    origin_match_index = origin_match_index[0]
    ref_s_map = [0]
    # 先计算以参考线起点为起点的ref_s_map
    for i in range(1, len(local_path_opt)):
        s = math.sqrt((local_path_opt[i][0] - local_path_opt[i - 1][0]) ** 2
                      + (local_path_opt[i][1] - local_path_opt[i - 1][1]) ** 2) + ref_s_map[-1]
        ref_s_map.append(s)
    # 然后算出在车辆当前位置投影点相对于参考线起点的s, 记为s0
    s0 = cal_projection_s_fun(local_path_opt, [origin_match_index], [origin_xy], ref_s_map)
    # ref_s_map 每一项都减去s0，这样就得到了所有匹配点相对于车辆投影点的s映射
    s_map = np.array(ref_s_map) - s0[0]
    return list(s_map)


def cal_s_l_fun(obs_xy_list: list, local_path_opt: list, s_map: list):
    """已验证
    这是坐标转换的通用模块
    坐标转换第一部分，计算S,L
    将障碍物的坐标转化为S-L坐标,也不一定必须是障碍物，可以使任何要坐标转化的对象
    基本步骤是
    0.确定车辆当前位置的投影作为坐标原点
    1.确定每个点的在参考线上的匹配点和投影点；
    2.计算S,S是投影点距离规划起点的弧长，就是连接这些离散点的折线长度；
    3.计算L,即障碍物与投影点的距离
    :param obs_xy_list: 给定一些障碍物对应点点的坐标
    :param local_path_opt: 优化后的参考线【(x_opt0, y_opt0, theta_0, kappa_0), ... 】
    # :param origin_xy: 车辆当前的位置
    :param s_map:
    :return:  输出s_list 和 l_list
    """
    # s_map = cal_s_map_fun(local_path_opt, origin_xy)  # 得到以车辆当前位置为起点的s_map

    # 计算这些障碍物点在当期参考线中匹配点的索引和投影点信息
    match_index_list, projection_list = match_projection_points(obs_xy_list, local_path_opt)

    s_list = cal_projection_s_fun(local_path_opt, match_index_list, obs_xy_list, s_map)  # 得到障碍点的s

    # 下面是计算l, 这里计算l和下面一个计算导数的函数有重复，以后可以考虑删除
    l_list = []

    for i in range(len(obs_xy_list)):
        pro_x, pro_y, theta, kappa = projection_list[i]  # 投影点的信息
        n_r = np.array([-math.sin(theta), math.cos(theta)])  # 投影点的单位法向量***************************************
        x, y = obs_xy_list[i]  # 待投影的位置
        r_h = np.array([x, y])  # 车辆实际位置的位矢
        r_r = np.array([pro_x, pro_y])  # 投影点的位置矢
        l_list.append(np.dot(r_h - r_r, n_r))  # UE4定义的是左手系，所以在车辆左侧的为负值

    return s_list, l_list


def cal_s_l_deri_fun(xy_list: list, V_xy_list: list, a_xy_list: list, local_path_xy_opt: list, origin_xy: tuple):
    """
    坐标转换第二部分，计算S对时间的导数，以及L对弧长的导数derivative
    基本步骤是
    0.确定车辆当前位置的投影作为坐标原点
    1.确定每个点的在参考线上的匹配点和投影点；
    2.计算S,S是投影点距离规划起点的弧长，就是连接这些离散点的折线长度；
    3.计算L,即障碍物与投影点的距离
    :param V_xy_list: velocity
    :param a_xy_list: acceleration
    :param xy_list: 给定一些对应点的坐标
    :param local_path_xy_opt: 优化后的参考线【(x_opt0, y_opt0, theta_0, kappa_0), ... 】
    :param origin_xy: 车辆当前的位置
    :return:  坐标变换的七个变量，每个对应一个列表
    """
    # 计算这些障碍物点在当期参考线中匹配点的索引和投影点信息
    match_index_list, projection_list = match_projection_points(xy_list, local_path_xy_opt)

    l_list = []  # store l
    dl_list = []  # store the derivative of l, dl/dt
    ds_list = []  # store the derivative of s, ds/dt
    ddl_list = []  # store the  second order derivative of l, d(dl/dt)/dt
    l_ds_list = []  # store the arc differential of l, dl/ds
    dds_list = []  # store the second order derivative of s, d(ds/dt)/dt
    l_dds_list = []  # store the second order arc differential of l, d(dl/ds)/ds
    for i in range(len(xy_list)):
        x, y, theta, kappa = projection_list[i]  # 投影点的信息
        nor_r = np.array([-math.sin(theta), math.cos(theta)])  # 投影点的单位法向量  **************************************
        tou_r = np.array([math.cos(theta), math.sin(theta)])  # 投影点的单位切向量
        r_h = np.array([origin_xy[0], origin_xy[1]])  # 车辆实际位置的位矢
        r_r = np.array([x, y])  # 投影点的位置矢

        """1.calculate l"""
        l = np.dot(r_h - r_r, nor_r)
        l_list.append(l)

        """2.calculate dl"""
        Vx, Vy = V_xy_list[i]
        V_h = np.array([Vx, Vy])  # 速度矢量
        dl = np.dot(V_h, nor_r)
        dl_list.append(dl)  # l对时间的导数

        """3.计算s对时间的导数"""
        ds = np.dot(V_h, tou_r) / (1 - kappa * l_list[i])
        ds_list.append(ds)

        """4.计算l对时间的二阶导数"""
        ax, ay = a_xy_list[i]
        a_h = np.array([ax, ay])
        ddl = np.dot(a_h, nor_r) - kappa * (1 - kappa * l) * (ds ** 2)
        ddl_list.append(ddl)

        """5.calculate the arc differential of l"""
        if abs(ds) < 1e-6:
            l_ds = 0
        else:
            l_ds = dl_list[i] / ds
        l_ds_list.append(l_ds)

        """6.calculate the second order derivative of s"""
        ax, ay = a_xy_list[i]
        a_h = np.array([ax, ay])
        kappa_ds = 0  # dk/ds, for simplicity, make it to be zero
        dds = (np.dot(a_h, tou_r) + 2 * (ds ** 2 * kappa * l_ds) + ds ** 2 * kappa_ds * l) / (1 - kappa * l)
        dds_list.append(dds)

        """7.the second order derivative of s"""
        if abs(ds) < 1e-6:
            l_dds = 0
        else:
            l_dds = (ddl - l_ds * dds) / (ds ** 2)
        l_dds_list.append(l_dds)

    return l_list, dl_list, ds_list, ddl_list, l_ds_list, dds_list, l_dds_list


def predict_block(ego_vehicle, ts=0.1):
    """
    预测车辆在下个规划周期的位置和航向
    :param ego_vehicle:
    :param ts: 预测时间长度
    :return: 返回车辆的直角坐标x, y和航向信息
    """
    vehicle_loc = ego_vehicle.get_location()
    x, y = vehicle_loc.x, vehicle_loc.y
    fi = ego_vehicle.get_transform().rotation.yaw*(math.pi/180)  # 车身横摆角，车轴和x轴的夹角
    V = ego_vehicle.get_velocity()  # 航向角是车速与x轴夹角
    V_length = math.sqrt(V.x*V.x + V.y*V.y + V.z*V.z)
    beta = math.atan2(V.y, V.x) - fi  # 质心侧偏角，车速和车轴之间的夹角
    # print("beta", beta, "fi", fi)
    V_y = V_length*math.sin(beta)  # 车速在车身坐标系下的分量
    V_x = V_length*math.cos(beta)
    # print("Vx", Vx, "Vy", Vy)
    x = x + V_x * ts * math.cos(fi) - V_y * ts * math.sin(fi)
    y = y + V_y * ts * math.cos(fi) + V_x * ts * math.sin(fi)
    fi_dao = ego_vehicle.get_angular_velocity().z * (math.pi / 180)
    fi = fi + fi_dao * ts

    return x, y, fi
