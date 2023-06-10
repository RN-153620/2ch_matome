############################################################################################################
# V1
# 2023/6/10
# ・ワードプレスで自動投稿
# ・自動ツイート＆自動フォロー機能
# TODO：サムネイル画像つける機能
# TODO：エラーハンドリング
# TODO：Printじゃなくてログ出力するようにする
############################################################################################################
#設定ファイル読み込み用
import configparser

#ブラウザ操作用
from selenium import webdriver
#recaptcha対策で常にログイン状態を保持するためにoptionでargumentが必要
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager 
from selenium.webdriver.common.by import By
from subprocess import CREATE_NO_WINDOW
#所定時間待機用
import time
#画像保存フォルダ作成用
#リンクファイル読み込み用
import csv
#selectタグを選択できるようにする
from selenium.webdriver.support.ui import Select
#絵文字駆逐用
import emoji
#エンターキーを押す用
from selenium.webdriver.common.keys import Keys
#chromeのユーザプロファイル新規作成用
import os
#Google画像検索取得用
from PIL import Image
import io
import requests
import hashlib
import random

# 共通設定ファイル読み込み
common_conf = configparser.ConfigParser(interpolation=None)
common_conf.read('./common_setting.conf', 'UTF-8')
conf_file = common_conf.get('conf', 'CONF_PATH')

#設定ファイル読み込み
conf = configparser.ConfigParser(interpolation=None)
conf.read(conf_file, 'UTF-8')

#既に投稿済みのリストを読み込み
filename = conf.get('root','PUBLISHED_THREADS_CSV')
published_threads = []
with open(filename, encoding='utf-8', newline='') as f:
    for row in csv.reader(f):
        published_threads.append(row[0])

#検索ワードのリストを読み込み
serach_words_filename = conf.get('root','SEARCH_WORDS_CSV')
serach_words = []
with open(serach_words_filename,encoding='utf-8') as f:
    for row in csv.reader(f):
        serach_words.append(row[0])

#chrome起動
chrome_section = 'chrome'
options = Options()
service = ChromeDriverManager().install()

#confファイルでユーザデータを利用する設定の場合、ユーザデータをセット
use_user_data = conf.get(chrome_section,'USE_USER_DATA') == '1'
if use_user_data:
    options.add_argument('--user-data-dir=' + conf.get(chrome_section,'USER_DATA_DIR'))
    options.add_argument('--profile-directory=' + conf.get(chrome_section,'PROFILE_DIRECTORY'))
    browser = webdriver.Chrome(service, options=options)
else:
    browser = webdriver.Chrome(service)

browser.implicitly_wait(1)

######################################################
# グローバル変数設定
######################################################


res_number = 0 #対象となるスレッドのレスの総数
thread_title = '' #wordpressの投稿の記事タイトルにする用
sammarize_is_succeeded = False #要約が成功したらTrue
img_is_existed = 0 #もしスレッド内に画像があったら、Google画像検索ではなくスレッド内の画像を使う


######################################################
# 過去ログでwordで検索した結果を取得
######################################################
def get_elems(word):
    """Get threds and reses of each threads.

    Keyword arguments:
    word -- search word
    """
    #まずは過去ログβの検索画面へ
    kakolog_section = 'kakolog'
    browser.get(conf.get(kakolog_section, 'URL'))
    time.sleep(5)
    print('Accessed kakolog-β.')

    word_input = browser.find_element(By.CSS_SELECTOR,conf.get(kakolog_section,'SEARCH_BOX_SELECTOR') )
    word_input.send_keys(word)
    word_input.send_keys(Keys.ENTER)
    time.sleep(15)

    #1ページ目の全てのスレッドのURLとレス数を取得
    #StaleElementReferenceExceptionを回避するために最初にリストを作成する
    nums = browser.find_elements(By.CSS_SELECTOR,conf.get(kakolog_section,'RES_NUM_SELECTOR'))
    res_counts = []
    for num in nums:
        res_counts.append(int(num.text))
    threads = browser.find_elements(By.CLASS_NAME,conf.get(kakolog_section,'THREAD_CLASS'))
    thread_urls = []
    for thread in threads:
        thread_urls.append(thread.get_attribute('href'))
    return thread_urls, res_counts


def get_thread_title(thread_url):
    """Access thred and get title."""
    #スレッドページへ
    browser.get(thread_url)
    print('Accessed thread.')
    time.sleep(8)
    return browser.find_element(By.CLASS_NAME, 'title').text

######################################################
# 過去ログでホットなスレッドを取得
######################################################
def get_reses(thread_url):
    """Get reses of thread by url."""
    reses = []
    
    #2ch.sc, 2ch.net, open2ch.net, bbspink.com でそれぞれ取得方法が異なるので注意！！
    if ('2ch.sc' in thread_url) or ('5ch.sc' in thread_url):
        elems = browser.find_elements(By.CSS_SELECTOR,'dd.net')
    elif ('2ch.net' in thread_url) or ('5ch.net' in thread_url):
        elems = browser.find_elements(By.CSS_SELECTOR,'span.escaped')
    elif ('open2ch.net' in thread_url) or ('open5ch.net' in thread_url):
        elems = browser.find_elements(By.CSS_SELECTOR,'dd.mesg')
    elif 'bbspink.com' in thread_url:
        elems = browser.find_elements(By.CSS_SELECTOR,'dd')
    
    for elem in elems:
        elemtext = elem.text
        #URLが混じっていると文章要約制度が落ちるので除外
        l_removed = [line for line in elemtext.splitlines() if not (('http' in line) or ('tp:/' in line) or ('jpg' in line) or ('tps:/' in line) or ('jpeg' in line) or ('bmp' in line) or ('gif' in line) or ('png' in line) or ('mpg' in line) or ('>>' in line))]
        reses.append(l_removed)
        reses.append('\n')

    #レスを一つの文字列に合体
    gathered_reses = []
    for i in range(len(reses)):
        gathered_res = '\n'.join(reses[i])
        #絵文字除去
        gathered_res = remove_emoji(gathered_res)
        gathered_reses.append(gathered_res)
    return gathered_reses

def remove_emoji(src_str):
    """Removing Emoji from string."""
    return ''.join(c for c in src_str if c not in emoji.EMOJI_DATA)

######################################################
# User Localサービスでレスから3行の要約を取得
######################################################

def get_sammary(reses):
    """Summarizing reses."""
    
    global sammarize_is_succeeded

    #UserLocalページへ
    user_local_section = 'user_local'
    browser.get(conf.get(user_local_section, 'URL'))
    print('Accessed User Local Text Mining')
    if use_user_data:
        print('Logged In')
    else:
        #IDとパスワードのフォームに入力
        elem = browser.find_element(By.ID,'email')
        elem.clear()
        elem.send_keys(conf.get(user_local_section,'USER'))
        elem = browser.find_element(By.NAME,'password')
        elem.clear()
        elem.send_keys(conf.get(user_local_section,'PASS'))
        print("Submittes login form")
    
        #ログインボタンを押してログイン
        browser_from = browser.find_element(By.NAME,'commit') #なぜかクリックできないので別の方法を使う
        browser_from.click()
        print("Pushed login button.")
    
    browser.implicitly_wait(5) #ここでエラー起きる事多いので長めにする

    #フォームに解析したいテキストを入力する
    elem = browser.find_element(By.ID,'docTextArea1')
    elem.clear()
    for i in range(len(reses)):
        elem.send_keys(reses[i])

    #テキストマイニングボタンを押して解析
    browser_from = browser.find_element(By.NAME,'analyze')
    browser_from.click()
    print("Analyzing...")
    time.sleep(5) #大体1秒くらいで終わるので3秒待てば十分

    #文章要約タブをクリック
    if len(browser.find_elements(By.CLASS_NAME,'result-frame-error')) >0:
        sammarize_is_succeeded = False
    else:
        elem = browser.find_element(By.XPATH,conf.get(user_local_section,'AUTO_SUMMARY_BTN_XPATH'))
        elem.click()

        #3行要約の文字列を取得
        time.sleep(10) #5秒くらいかかる時あったので長めにしておく
        elem = browser.find_element(By.XPATH,conf.get(user_local_section,'AUTO_SUMMARY_TEXT_XPATH')).text
        yoyaku_3 = elem.splitlines()
        
        #要約成功フラグ
        sammarize_is_succeeded = True

        return yoyaku_3

######################################################
# まとめくすでまとめ記事作成
######################################################

#user_localで取得した要約たちを含むレスとその前後のレスを取得する
def get_matome(board_url, yoyakus):
    global img_is_existed

    #まとめくす　ログイン情報
    mtmx_section = 'mtmex'
    MTMX_USER = conf.get(mtmx_section, 'USER')
    MTMX_PASS = conf.get(mtmx_section, 'PASS')

    img_is_existed = 0
    yoyaku_is_empty = 0 #要約に成功したら1
    
    #まとめくすログインページにアクセス
    browser.get(conf.get(mtmx_section, 'URL'))
    time.sleep(1)
    print('Accesed Matomex')

    if not use_user_data:
        input_email = browser.find_element(By.XPATH,conf.get(mtmx_section,'EMAIL_XPATH'))
        input_email.send_keys(MTMX_USER)

        input_password = browser.find_element(By.XPATH,conf.get(mtmx_section,'PASSWORD_XPATH'))
        input_password.send_keys(MTMX_PASS)

        login_btn = browser.find_element(By.XPATH, conf.get(mtmx_section,'LOGIN_BTN_XPATH'))
        login_btn.click()


    #スレッドを取得
    elem = browser.find_element(By.ID,'ready_ourl')
    elem.clear()
    elem.send_keys(board_url)
    
    time.sleep(1)

    #なぜかいつものクリックメソッドだと直接クリックできなかったのでjavascriptで場所取得して直接クリック 
    elements = browser.find_element(By.ID,'ready_get')
    elements.send_keys(Keys.ENTER)

    #「スレッドを取得しました」のポップアップウィンドウが消えるまで待機
    time.sleep(12)

    #「エラー: このスレッドを利用したまとめ記事の作成は禁止されています。」と出た場合はskipする
    elem = browser.find_element(By.XPATH,conf.get(mtmx_section,'ERROR_XPATH')).text
    if conf.get(mtmx_section, 'ERROR_MSG') in elem:
        print('Matome is prohibited')
        return False
    else:
        #3行要約を含むレス番号を取得
        yoyaku_indexes = []
        elems = browser.find_elements(By.CLASS_NAME,'description')

        for elem in elems:
            #レス数が少なすぎて要約できなかった場合は全てのレスを取得する
            if yoyakus is None: 
                yoyaku_is_empty = 1
                yoyaku_index = 0 #最初の投稿を中心にする
                yoyaku_indexes.append(yoyaku_index)        
            else: 
                yoyaku_is_empty = 0
                for yoyaku in yoyakus:
                    #もし要約したリストが含まれていたらそのレス番号を取得
                    if yoyaku in elem.text:
                        yoyaku_index = elems.index(elem)
                        yoyaku_indexes.append(yoyaku_index)

        #3行要約を含むコメントの前後3つのレスを取得
        pick_indexes = []
        pick_indexes.append(0) #スレッドの最初の投稿は必ず入れる
        remove_indexes = []
        print('Reses include sammary：', len(pick_indexes))
        for i in range(len(yoyaku_indexes)):
            for j in range(-8,9): #要約文に含まれるレスの前後8個を取得
                pick_indexes.append(yoyaku_indexes[i]+j)

        #重複を削除
        pick_indexes = list(set(pick_indexes)) #setは重複を持たないデータ型である。それを介して、再びリストに戻すことで重複を削除できる

        #インデックスがマイナスのものと、リストの数を超えたものは削除
        for i in range(len(pick_indexes)):
            if pick_indexes[i] < 0:
                #remove_index = pick_indexes[i]
                remove_index = i
                remove_indexes.append(remove_index)
            elif pick_indexes[i] >= res_number:
                #remove_index = pick_indexes[i]
                remove_index = i
                remove_indexes.append(remove_index)

        #リストの中の指定のインデックスを削除する関数を作って、リストから削除する
        dellist = lambda items, indexes: [item for index, item in enumerate(items) if index not in indexes]
        pick_indexes = dellist(pick_indexes,remove_indexes)
        
        #レスが少なすぎて要約を失敗する時は全てのレスをチェックいれる
        if yoyaku_is_empty == 1:
           for i in range(res_number):
               pick_indexes.append(i)
        
        #どんどん追加されてしまうので最初に削除してから追加する
        elem = browser.find_element(By.XPATH, conf.get(mtmx_section, 'API_XPATH'))
        select_elem = Select(elem)
        select_elem.select_by_value('1')

        ###投稿するレスにチェックを入れていく
        print('Selecting reses')
        for pick_index in pick_indexes:
            ##################################### ロジック部 #####################################           
            elem = browser.find_elements(By.CLASS_NAME,'description')[pick_index] #それぞれのレスを取得
            
            #文字数が所定の文字数以上は除去(ただし1つ目の投稿は良しとする)
            if len(elem.text) > 120:
                print(str(pick_index) + 'must less than 120 characters')
                if pick_index == 0: #最初の投稿は長すぎても許容する
                    elem = browser.find_elements(By.CLASS_NAME,'selects')[pick_index]
                    browser.execute_script("arguments[0].click();", elem)
            
            #問題ないレスの場合のみチェック入れる
            else:
                #画面外にあるとクリックできないのでexecute_script使ってjavascript使ってクリック
                #elem = browser.find_element_by_id('ck'+str(pick_index+1))
                elem = browser.find_elements(By.CLASS_NAME,'selects')[pick_index]
                browser.execute_script("arguments[0].click();", elem)
            
                ##################################### 画像アップロード#####################################

                #レスに画像がある場合は合わせてアップする
                btnelems = browser.find_elements(By.XPATH,'/html/body/div/div[4]/div['+str(pick_index+1)+']/div[2]/span/input')
                if len(btnelems) > 0:
                    print('画像あるよ')
                    img_is_existed = 1 #画像が存在した場合はGoogle画像検索の画像は使用しない
                    for i in range(len(btnelems)):
                        btnelems[i].send_keys(Keys.ENTER)
                        print('ボタンクリックされたよ')
                        time.sleep(7)

        #ポップアップが邪魔で設定ボタンが押せなかったのでしばらく待機する
        time.sleep(12)

        #ここまではiframeの中に入ってる。API設定は外にあるので出る必要あり
        browser.switch_to.default_content()

        #名前を全てサイト名に変更する
        elem = browser.find_element(By.ID,'pubopt_switch').send_keys(Keys.ENTER)
        elem = browser.find_element(By.ID,'pubopt_namedefault')
        elem.clear()
        elem.send_keys(conf.get(mtmx_section, 'RESS_USER'))

        #下記ドメインの設定や設定ボタンのクリックが反応しない事があったので少し待機する
        time.sleep(1)

        #タグ発行ボタンを押す
        elem = browser.find_element(By.XPATH,conf.get(mtmx_section, 'TAG_ISSUE_XPATH')).click()
        time.sleep(1)

        #下書き投稿
        elem = browser.find_element(By.XPATH, conf.get(mtmx_section, 'DRAFT_PUB_BTN_XPATH')).click()
        print('Publishing Draft...')
        return True

######################################################
# キャプチャ画像取得：未使用の機能。TODO サムネイル画像取得&公開
######################################################

#キャプチャ画像のパス
file_path = 'hoge' #cron用

def get_capt(word): #https://qiita.com/maruman029/items/8dc7f8190d0e3f892d99
    global file_path
    # クリックなど動作後に待つ時間(秒)
    sleep_between_interactions = 4
    # ダウンロードする枚数
    download_num = 1
    # 検索ワード
    query = word
    # 画像検索用のurl
    search_url = "https://www.google.com/search?safe=off&site=&tbm=isch&source=hp&q={q}&oq={q}&gs_l=img"

    # サムネイル画像のURL取得
    #wd = webbrowser.Chrome(executable_path='/usr/local/bin/chromebrowser')
    browser.get(search_url.format(q=query))
    # サムネイル画像のリンクを取得(ここでコケる場合はセレクタを実際に確認して変更する)
    thumbnail_results = browser.find_elements(By.CLASS_NAME,"img.rg_i")

    # サムネイルをクリックして、各画像URLを取得
    image_urls = set()
    #取得する画像をランダム化する
    pick_num = random.randint(1,25) #30枚目までのランダムな画像を取得 →30だと画像撮れなかったので25あたりにしておく
    print(pick_num)
    #for img in thumbnail_results[:download_num]:
    for img in thumbnail_results:
        print(img)
        try:
            img.click()
            time.sleep(sleep_between_interactions)
            print('Google画像検索のイメージをクリックしました')
        except Exception:
            print('Exception発生！！')
            continue
        # 一発でurlを取得できないので、候補を出してから絞り込む(やり方あれば教えて下さい)
        # 'n3VNCb'は変更されることあるので、クリックした画像のエレメントをみて適宜変更する
        url_candidates = browser.find_elements(By.CLASS_NAME,'n3VNCb')
        for candidate in url_candidates:
            url = candidate.get_attribute('src')
            print(url)
            if url and 'https' in url:
                #jpg形式限定 できればpng,gifとかも読み込みたいが、、
                #if ('jpg' or 'jpeg' or 'JPG' or 'JPEG') in url:
                image_urls.add(url)
    # 少し待たないと正常終了しなかったので3秒追加
    time.sleep(sleep_between_interactions+3)
    #browser.quit()

    # 画像のダウンロード
    #image_save_folder_path = 'data'
    image_save_folder_path = 'hoge' #cronの場合は絶対パスなので注意！！
    for url in image_urls:
        try:
            image_content = requests.get(url).content
        except Exception as e:
            print(f"ERROR - Could not download {url} - {e}")

        try:
            image_file = io.BytesIO(image_content)
            image = Image.open(image_file).convert('RGB')
            file_path = os.path.join(image_save_folder_path,hashlib.sha1(image_content).hexdigest()[:10] + '.jpg')
            print(file_path)
            with open(file_path, 'wb') as f:
                image.save(f, "JPEG", quality=90)
            print(f"SUCCESS - saved {url} - as {file_path}")
        except Exception as e:
            print(f"ERROR - Could not save {url} - {e}")

######################################################
# Wordpress設定
######################################################

def publish_to_wordpress(word):
    site_section = 'site'
    site_url = conf.get(site_section, 'URL')

    global file_path
    global img_is_existed

    wp_section = 'wordpress'
    USER = conf.get(wp_section, 'USER')
    PASS = conf.get(wp_section, 'PASS')

    #wordpressログインページにアクセス
    url_login= site_url + "/wp-admin"
    browser.get(url_login)
    time.sleep(1)
    print('Accessed WordPress Login Window.')

    #IDとパスワードのフォームに入力
    if not use_user_data:
        elem = browser.find_element(By.ID,'user_login')
        elem.clear()
        elem.send_keys(USER)
        elem = browser.find_element(By.ID,'user_pass')
        elem.clear()
        elem.send_keys(PASS)

        #ログインボタンを押してログイン
        browser.find_element(By.ID,'wp-submit').click()
        print("Pushed login button.")

    #投稿ページにアクセス （下書きの記事のみ表示）
    url_login= site_url + conf.get(wp_section, 'DRAFT')
    browser.get(url_login)
    print('Accessed WordPress Admin Window.')
    time.sleep(3) #1だとエラーが出たため念のため長めにしてる
    
    elem = browser.find_elements(By.CLASS_NAME,'row-title')
    title = elem[0].text #投稿1つ目のタイトル

    #スレッドのタイトル
    if not thread_title in title:
        print('Publishing draft is failed.')
        return False
    else:
        print('Publishing draft is succeded')
        browser.get(elem[0].get_attribute('href'))
                                                         
            #アイキャッチ画像の設定
            #スレッド内に画像があった時はその画像を使うのでこの工程はスキップ
            # if not img_is_existed:
            #     #https://www.dafuku.com/2014/12/selenium-file-upload.html
            #     #メディア追加ボタンをクリックしてキャプチャを追加
            #     elem = browser.find_element(By.ID,'insert-media-button').send_keys(Keys.SPACE)
            #     time.sleep(5)
            #     #アイキャッチ画像をクリック
            #     elem = browser.find_element(By.ID,'menu-item-featured-image').send_keys(Keys.SPACE)
            #     #elem = browser.find_element_by_id('menu-item-featured-image').click()
            #     time.sleep(1)
            #     #elem = browser.find_element_by_id('html5_1egqrmdn0sirpvd143g6i41l3g3').send_keys('hoge' + file_path)
            #     #elem = browser.find_element_by_xpath('//*[@id="__wp-uploader-id-0"]//*[@class="moxie-shim moxie-shim-html5"]//input').send_keys('hoge' + file_path)
            #     elem = browser.find_element(By.XPATH,'//*[@id="__wp-uploader-id-0"]//*[@class="moxie-shim moxie-shim-html5"]//input').send_keys(file_path)
            #     time.sleep(10) #7秒だとエラーが出た

            #     #画像ファイルによっては'このファイルタイプはセキュリティ上の理由から、許可されていません。'と表示され、ボタンが押せない。ボタンが押せない場合は無視する
            #     if len(browser.find_elements(By.XPATH,'//*[@id="__wp-uploader-id-0"]/div[4]/div/div[2]/button')) > 0:
            #         elem = browser.find_element_by_xpath('//*[@id="__wp-uploader-id-0"]/div[4]/div/div[2]/button').send_keys(Keys.ENTER)
            #         print('ボタンを押したよ！！')
        #カテゴリボタンをクリック
        category_btn = browser.find_element(By.XPATH, conf.get(wp_section, 'CATEGORY_BTN_XPATH'))
        if(category_btn.get_attribute('aria-expanded') == 'false'):
            category_btn.click()
        time.sleep(1)

        #カテゴリの一覧を取得
        categories = browser.find_elements(By.CLASS_NAME, conf.get(wp_section,'CATEGORY_CHECKBOX_CLASS'))
        for category in categories:
            if(word==category.text):
                category.click()

        #公開ボタンをクリック
        browser.find_element(By.XPATH,conf.get(wp_section,'PUBLISH_BTN_XPATH')).send_keys(Keys.ENTER)
        print('Publishing article is succeded')
        time.sleep(5)

        #最新の投稿ページに遷移
        first_article = browser.find_element(By.XPATH, conf.get(wp_section,'PUBLISHED_ART_XPATH')).get_attribute('href')
        browser.get(first_article)
        print('Moved to published article')
        time.sleep(5)

        #Twitterシェアボタン押下
        twitter_btn = browser.find_element(By.XPATH, conf.get(wp_section,'TWT_SHARE_BTN_XPATH')).get_attribute('href')
        browser.get(twitter_btn)
        print('Get to Twitter')
        time.sleep(5)
        return True


######################################################
# Twitterに投稿
######################################################
def share_to_twitter():
    #Tweetボタン押下
    twt_section = 'twitter'
    # 自動シェア機能を使用する場合のみ
    if conf.get(twt_section, 'USR_AUTO_SHERE') == '1':
        browser.find_element(By.XPATH, conf.get(twt_section, 'TWT_BTN_XPATH')).click()
        print('Tweet is succeded')
        time.sleep(10)
        # 自動フォロー機能を使用する場合のみ
        if conf.get(twt_section, 'USR_AUTO_FOLLOW') == '1':
            #Tweetのついでに3人フォロー ※画面外の要素はクリックできないのでecexute_scriptを使用
            follow_btn_1 = browser.find_element(By.XPATH, conf.get(twt_section, 'FOLLOW_ONE_XPATH'))
            browser.execute_script("arguments[0].click();", follow_btn_1)
            time.sleep(2)
            follow_btn_2 = browser.find_element(By.XPATH, conf.get(twt_section, 'FOLLOW_TWO_XPATH'))
            browser.execute_script("arguments[0].click();", follow_btn_2)
            time.sleep(2)
            follow_btn_3 = browser.find_element(By.XPATH, conf.get(twt_section, 'FOLLOW_THREE_XPATH'))
            browser.execute_script("arguments[0].click();", follow_btn_3)
            time.sleep(2)

######################################################
# 一連の流れを実行
######################################################
for word in serach_words:
    #wordで検索した1ページ目のスレッド一覧取得
        all_elems = get_elems(word)
        thread_urls = all_elems[0]
        nums = all_elems[1]

        for i,thread_url in enumerate(thread_urls):
            res_number = nums[i]
            if res_number < 10:
                print('It must exist greater than 10 reses in thread, but ', thread_url, ' has only', res_number)
                continue
            thread_title = get_thread_title(thread_url)
            if thread_title in published_threads:
                print('The title is already published：', thread_title)
                continue
            print(thread_title, ' is writen to ', filename)
            published_threads.append(thread_title)
            with open(filename, 'a', newline="", encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([thread_title])

            #レス取得
            reses = get_reses(thread_url)

            #レスを要約
            sammary = get_sammary(reses)
            #要約が成功した時だけ先に進む
            if sammarize_is_succeeded:
                #まとめくすで下書き投稿出来たらwordpressに投稿
                matome_is_succeeded = get_matome(thread_url, sammary)
                if matome_is_succeeded:
                    if publish_to_wordpress(word):
                        share_to_twitter()
                else:
                    continue
                    #まずはキャプチャを取得
                    # getCapt(word)
                        
            print('\n')
            time.sleep(3)
print('DONE')
browser.quit()