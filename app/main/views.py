from flask import render_template, redirect, url_for, abort, flash, request,\
    current_app, make_response
from flask_login import login_required, current_user
from flask_sqlalchemy import get_debug_queries
from . import main
from .forms import EditProfileForm, EditProfileAdminForm, PostForm,\
    CommentForm
from .. import db
from ..models import Permission, Role, User, Post, Comment,Ranking,Movie
from ..decorators import admin_required, permission_required


@main.after_app_request
def after_request(response):
    for query in get_debug_queries():
        if query.duration >= current_app.config['FLASKY_SLOW_DB_QUERY_TIME']:
            current_app.logger.warning(
                'Slow query: %s\nParameters: %s\nDuration: %fs\nContext: %s\n'
                % (query.statement, query.parameters, query.duration,
                   query.context))
    return response


@main.route('/shutdown')
def server_shutdown():
    if not current_app.testing:
        abort(404)
    shutdown = request.environ.get('werkzeug.server.shutdown')
    if not shutdown:
        abort(500)
    shutdown()
    return 'Shutting down...'

# modify
def create_data():
    ranks=Ranking.query()
    data ={}
    for rank in ranks:
        data.setdefault(rank.user_id,{})
        data[rank.user_.id][rank.movie_id]=rank.rank
    return data

def transformdata(data):
    '''
    物品之间的相似度 与 用户之间的相似度 求解 一样。故只需要将用户换成物品即可
    '''   
    newdata = {}
    users ={}
    for person in data:
        for movie in data[person]:
            #初始化
            newdata.setdefault(movie,{})
            #物品与用户对调
            newdata[movie][person] = data [person][movie]  #字典可以直接写[key]，就表示插入key值了。非常简便
    return newdata

def sim_pearson(data,person1,person2):
    '''
    计算上面格式的数据 里的  两个用户 相似度.
    基于用户过滤思路：找出两个用户看过的相同电影的评分，从而进行按pearson公式求值。那些非公共电影不列入求相似度值范围。
    基于物品过滤思路：找过两部电影相同的观影人给出的评分，从而按pearson公式求值
    返回：评分的相似度，[-1,1]范围，0最不相关，1，-1为正负相关，等于1时，表示两个用户完全一致评分
    这里的data格式很重要，这里计算相似度是严格按照上面data格式所算。
    此字典套字典格式，跟博客计算单词个数 存储格式一样 
    '''
    #计算pearson系数，先要收集两个用户公共电影名单
    #commonmovies = [ movie for movie in data[person1] if movie in data[person2]] 分解步骤为如下：
    commonmovies = []         #改成列表呢
    for movie in data[person1]:     #data[person1]是字典，默认第一个元素 in （字典）是指 key.所以这句话是指 对data[person1]字典里遍历每一个key=movie
        if movie in data[person2]:  #data[person2]也是字典，表示该字典有key是movie.  
            commonmovies.append(movie)   # commonmovie是  两个用户的公共电影名的列表
    
    #看过的公共电影个数
    n = float(len(commonmovies))
    if n==0: 
        return 0
    
    '''下面正是计算pearson系数公式 '''
    #分布对两个用户的公共电影movie分数总和
    sum1 = sum([data[person1][movie]for movie in commonmovies ])  
    sum2 = sum([data[person2][movie]for movie in commonmovies])
    
    #计算乘积之和
    sum12 = sum([data[person1][movie]*data[person2][movie] for movie in commonmovies])
    
    #计算平方和
    sum1Sq = sum([ pow(data[person1][movie],2 ) for movie in commonmovies ])        
    sum2Sq = sum([ pow(data[person2][movie],2 ) for movie in commonmovies ]) 
    
    #计算分子        
    num = sum12 - sum1*sum2/n
    #分母
    den = sqrt((sum1Sq - pow(sum1,2)/n)*(sum2Sq - pow(sum2,2)/n))
    if den==0:  return 0                
    
    return num/den

#为单个电影物品返回最匹配结果
def topmatches(data,givenperson ,returnernum = 5,simscore = sim_pearson):
    '''
    用户匹配推荐：给定一个用户，返回对他口味最匹配的其他用户
    物品匹配： 给定一个物品，返回相近物品
    输入参数：对person进行默认推荐num=5个用户（基于用户过滤），或是返回5部电影物品（基于物品过滤），相似度计算用pearson计算
    '''
    #建立最终结果列表
    usersscores =[(simscore(data,givenperson,other),other) for other in data if other != givenperson ]
    #对列表排序
    usersscores.sort(cmp=None, key=None, reverse=True)
    
    return usersscores[0:returnernum]


#从为单一物品返回匹配结果 扩展到 为所有物品返回匹配结果
def calSimilarItems(data,num=10):
#以物品为中心，对偏好矩阵转置
    moviedata = transformdata(data)
    ItemAllMatches = {}
    for movie in moviedata:
         ItemAllMatches.setdefault(movie,[])
         #对每个电影 都求它的匹配电影集,求电影之间的距离用欧式距离，用pearson距离测出的结果是不一样的
         ItemAllMatches[movie] = topmatches(moviedata, movie, num,simscore = sim_distance)
    return ItemAllMatches

# 推荐用户没看过的电影，物品过滤 
def getrecommendations(data,targetperson,moviesAllsimilarity):
    '''
    输入movieAllSimilarity就是上面calsimilarItems已经计算好的所有物品之间的相似度数据集：
     '''
    #获得所有物品之间的相似数据集
    scoresum = {}
    simsum = {}
    #遍历所有看过的电影
    for watchedmovie in data[targetperson]:
        rating = data[targetperson][watchedmovie]
        #遍历与当前电影相近的电影
        for(similarity,newmovie) in moviesAllsimilarity[watchedmovie]:   #取一对元组
            #已经对当前物品评价过，则忽略
            if newmovie in data[targetperson] :continue
           
            scoresum.setdefault(newmovie,0)
            simsum.setdefault(newmovie,0)
            #全部相似度求和
            simsum[newmovie] += similarity
            #评价值与相似度加权之和
            scoresum[newmovie] += rating * similarity
            
    rankings = [(score/simsum[newmovie] , newmovie) for newmovie,score in scoresum.items() ]
    rankings.sort(cmp=None, key=None, reverse=True)
    return rankings

# 推荐用户未看过电影，用户过滤
def recommendItems(data,givenperson,num =5 ,simscore = sim_pearson):
    '''
    物品推荐：给定一个用户person,默认返回num=5物品
    要两个for,对用户，物品 都进行 遍历
    '''
    #所有变量尽量用字典，凡是列表能表示的字典都能表示，那何不用字典
    itemsimsum={} 
    #存给定用户没看过的电影的其他用户评分加权
    itemsum={}
#遍历每个用户，然后遍历该用户每个电影
    for otheruser in data :
        #不要和自己比较
        if otheruser == givenperson:   continue
        #忽略相似度=0或小于0情况
        sim = simscore(data,givenperson,otheruser)
        if sim <=0:   continue
        
        for itemmovie in data[otheruser]:
            #只对用户没看过的电影进行推荐，参考了其他用户的评价值（协同物品过滤是参考了历史物品相似度值）
            if itemmovie not in data[givenperson]:
                #一定要初始化字典：初始化itemsum与itemsimsum
                itemsum.setdefault(itemmovie,0)
                itemsimsum.setdefault(itemmovie,0)
                #用户相似度*评价值
                itemsum[itemmovie] += sim  * data[otheruser][itemmovie]
                itemsimsum[itemmovie] += sim 
     
    #最终结果列表，列表包含一元组（item,分数）
    rankings = [(itemsum[itemmovie] / itemsimsum[itemmovie],itemmovie) for itemmovie in  itemsum]
    #结果排序
    rankings.sort(cmp=None, key=None, reverse=True);
    return rankings

@main.route('/', methods=['GET', 'POST'])
def index():
    page = request.args.get('page', 1, type=int)
    show_all = True
    show_userrecommend = False
    show_itemrecommend = False
    if current_user.is_authenticated:
        show_userrecommend = bool(request.cookies.get('userrecommend', ''))
        show_itemrecommend = bool(request.cookies.get('itemrecommend', ''))

    if show_all:
        query = Movie.query
    elif show_userrecommend:
        query = current_user.followed_posts
    else:
        pass
        
    pagination = query.paginate(
        page, per_page=current_app.config['FLASKY_MOVIES_PER_PAGE'],
        error_out=False)
    movies = pagination.items
    return render_template('index.html', movies=movies,
                           show_all=show_all, pagination=pagination, show_userrecommend=show_userrecommend,
                           show_itemrecommend=show_itemrecommend)


@main.route('/user/<username>')
def user(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    pagination = user.posts.order_by(Post.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_POSTS_PER_PAGE'],
        error_out=False)
    posts = pagination.items
    return render_template('user.html', user=user, posts=posts,
                           pagination=pagination)


@main.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user._get_current_object())
        db.session.commit()
        flash('Your profile has been updated.')
        return redirect(url_for('.user', username=current_user.username))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', form=form)


@main.route('/edit-profile/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        db.session.commit()
        flash('The profile has been updated.')
        return redirect(url_for('.user', username=user.username))
    form.email.data = user.email
    form.username.data = user.username
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template('edit_profile.html', form=form, user=user)


@main.route('/post/<int:id>', methods=['GET', 'POST'])
def post(id):
    post = Post.query.get_or_404(id)
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data,
                          post=post,
                          author=current_user._get_current_object())
        db.session.add(comment)
        db.session.commit()
        flash('Your comment has been published.')
        return redirect(url_for('.post', id=post.id, page=-1))
    page = request.args.get('page', 1, type=int)
    if page == -1:
        page = (post.comments.count() - 1) // \
            current_app.config['FLASKY_COMMENTS_PER_PAGE'] + 1
    pagination = post.comments.order_by(Comment.timestamp.asc()).paginate(
        page, per_page=current_app.config['FLASKY_COMMENTS_PER_PAGE'],
        error_out=False)
    comments = pagination.items
    return render_template('post.html', posts=[post], form=form,
                           comments=comments, pagination=pagination)


@main.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    post = Post.query.get_or_404(id)
    if current_user != post.author and \
            not current_user.can(Permission.ADMIN):
        abort(403)
    form = PostForm()
    if form.validate_on_submit():
        post.body = form.body.data
        db.session.add(post)
        db.session.commit()
        flash('The post has been updated.')
        return redirect(url_for('.post', id=post.id))
    form.body.data = post.body
    return render_template('edit_post.html', form=form)


@main.route('/follow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def follow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    if current_user.is_following(user):
        flash('You are already following this user.')
        return redirect(url_for('.user', username=username))
    current_user.follow(user)
    db.session.commit()
    flash('You are now following %s.' % username)
    return redirect(url_for('.user', username=username))


@main.route('/unfollow/<username>')
@login_required
@permission_required(Permission.FOLLOW)
def unfollow(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    if not current_user.is_following(user):
        flash('You are not following this user.')
        return redirect(url_for('.user', username=username))
    current_user.unfollow(user)
    db.session.commit()
    flash('You are not following %s anymore.' % username)
    return redirect(url_for('.user', username=username))


@main.route('/followers/<username>')
def followers(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followers.paginate(
        page, per_page=current_app.config['FLASKY_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.follower, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title="Followers of",
                           endpoint='.followers', pagination=pagination,
                           follows=follows)


@main.route('/followed_by/<username>')
def followed_by(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        flash('Invalid user.')
        return redirect(url_for('.index'))
    page = request.args.get('page', 1, type=int)
    pagination = user.followed.paginate(
        page, per_page=current_app.config['FLASKY_FOLLOWERS_PER_PAGE'],
        error_out=False)
    follows = [{'user': item.followed, 'timestamp': item.timestamp}
               for item in pagination.items]
    return render_template('followers.html', user=user, title="Followed by",
                           endpoint='.followed_by', pagination=pagination,
                           follows=follows)


@main.route('/all')
@login_required
def show_all():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_all', '1', max_age=30*24*60*60)
    resp.set_cookie('show_userrecommend', '', max_age=30*24*60*60)
    resp.set_cookie('show_itemrecommend', '', max_age=30*24*60*60)
    return resp


@main.route('/userrecommend')
@login_required
def show_userrecommend():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_userrecommend', '1', max_age=30*24*60*60)
    resp.set_cookie('show_itemrecommend', '', max_age=30*24*60*60)
    resp.set_cookie('show_all', '', max_age=30*24*60*60)
    return resp

@main.route('/itemrecommend')
@login_required
def show_itemrecommend():
    resp = make_response(redirect(url_for('.index')))
    resp.set_cookie('show_all', '', max_age=30*24*60*60)
    resp.set_cookie('show_userrecommend', '', max_age=30*24*60*60)
    resp.set_cookie('show_itemrecommend', '1', max_age=30*24*60*60)
    return resp


@main.route('/moderate')
@login_required
@permission_required(Permission.MODERATE)
def moderate():
    page = request.args.get('page', 1, type=int)
    pagination = Comment.query.order_by(Comment.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_COMMENTS_PER_PAGE'],
        error_out=False)
    comments = pagination.items
    return render_template('moderate.html', comments=comments,
                           pagination=pagination, page=page)


@main.route('/moderate/enable/<int:id>')
@login_required
@permission_required(Permission.MODERATE)
def moderate_enable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = False
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('.moderate',
                            page=request.args.get('page', 1, type=int)))


@main.route('/moderate/disable/<int:id>')
@login_required
@permission_required(Permission.MODERATE)
def moderate_disable(id):
    comment = Comment.query.get_or_404(id)
    comment.disabled = True
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('.moderate',
                            page=request.args.get('page', 1, type=int)))


