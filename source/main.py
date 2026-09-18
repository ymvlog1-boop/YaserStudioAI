import sys, json, copy, traceback, threading
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QRectF, QTranslator, QLocale, QSettings
from PySide6.QtGui import QImage,QPixmap,QPen,QColor,QPainter,QKeySequence,QShortcut,QFontDatabase,QFont,QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
 QListWidget,QListWidgetItem,QSlider,QFileDialog,QMessageBox,QGraphicsView,QGraphicsScene,QComboBox,
 QCheckBox,QProgressBar,QScrollArea,QFrame,QSplitter,QTabWidget,QInputDialog)
import engine
import updater, subprocess, os

class Signals(QObject):
    done=Signal(object);error=Signal(str);progress=Signal(int,str)
class Job(QRunnable):
    def __init__(self,fn):super().__init__();self.fn=fn;self.signals=Signals()
    def run(self):
        try:self.signals.done.emit(self.fn(self.signals))
        except Exception:self.signals.error.emit(traceback.format_exc())

class Canvas(QGraphicsView):
    stroke=Signal(object)
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.pix=None;self.faces=[];self.mode='view';self.brush=25;self.active=None;self.zoomed=False
        self.setRenderHint(QPainter.RenderHint.Antialiasing);self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor('#10151f'));self.setMinimumSize(420,400)
    def show_image(self,rgb):
        h,w=rgb.shape[:2];im=QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()
        self.scene().clear();self.pix=self.scene().addPixmap(QPixmap.fromImage(im));self.scene().setSceneRect(0,0,w,h)
        if not self.zoomed:self.fitInView(self.pix,Qt.AspectRatioMode.KeepAspectRatio)
    def draw_faces(self,faces):
        if not self.pix:return
        w=self.pix.pixmap().width();h=self.pix.pixmap().height()
        for i,f in enumerate(faces or []):
            x,y,fw,fh=f['box'];color=QColor('#4fd6b0' if f['enabled'] else '#ed8796');pen=QPen(color,2);pen.setCosmetic(True)
            self.scene().addRect(x*w,y*h,fw*w,fh*h,pen)
            t=self.scene().addText(str(i+1));t.setDefaultTextColor(color);t.setPos(x*w,y*h)
    def set_mode(self,mode):
        self.mode=mode;self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode=='view' else QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.ArrowCursor if mode=='view' else Qt.CursorShape.CrossCursor)
    def point(self,event):
        p=self.mapToScene(event.position().toPoint());r=self.sceneRect()
        if not r.contains(p):return None
        return [p.x()/r.width(),p.y()/r.height()]
    def paint_segment(self,a,b):
        r=self.sceneRect();color=QColor(246,127,115,165) if self.mode in ('remove','bg_erase','local_darken') else QColor(65,207,174,140)
        if self.mode in ('local_brighten','local_saturate'):color=QColor(255,201,91,165)
        if self.mode=='bg_add':color=QColor(72,170,255,165)
        if self.mode=='erase':color=QColor(255,200,80,180)
        pen=QPen(color,max(1,self.brush/1000*min(r.width(),r.height())));pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.scene().addLine(a[0]*r.width(),a[1]*r.height(),b[0]*r.width()+.01,b[1]*r.height()+.01,pen)
    def mousePressEvent(self,e):
        if self.mode!='view' and self.pix and e.button()==Qt.MouseButton.LeftButton:
            p=self.point(e)
            if p:self.active={'points':[p],'size':self.brush/1000,'erase':self.mode=='erase'};self.paint_segment(p,p)
        else:super().mousePressEvent(e)
    def mouseMoveEvent(self,e):
        if self.active:
            p=self.point(e)
            if p:self.paint_segment(self.active['points'][-1],p);self.active['points'].append(p)
        else:super().mouseMoveEvent(e)
    def mouseReleaseEvent(self,e):
        if self.active:
            s=self.active;self.active=None;self.stroke.emit(s)
        else:super().mouseReleaseEvent(e)
    def wheelEvent(self,e):
        factor=1.2 if e.angleDelta().y()>0 else 1/1.2
        current=self.transform().m11()
        if .025<current*factor<20:self.scale(factor,factor);self.zoomed=True
    def fit(self):
        self.zoomed=False
        if self.pix:self.fitInView(self.pix,Qt.AspectRatioMode.KeepAspectRatio)
    def resizeEvent(self,e):
        super().resizeEvent(e)
        if not self.zoomed:self.fit()

STYLE='''
QWidget {background:#161d29;color:#e9eef6;font-family:"Noto Sans Arabic";font-size:14px;}
QMainWindow{background:#10151f;} QLabel#brand{font-size:25px;font-weight:700;color:#ffffff;}
QLabel#muted{color:#91a1b8;font-size:12px;} QLabel#section{color:#64d9bd;font-weight:600;font-size:16px;}
QPushButton{background:#263348;border:1px solid #35445b;border-radius:7px;padding:9px 12px;}
QPushButton:hover{background:#34465e;} QPushButton:checked{background:#246255;border-color:#64d9bd;}
QPushButton#primary{background:#38b998;color:#071e19;font-weight:700;} QPushButton:disabled{color:#637086;background:#202735;}
QListWidget{background:#101722;border:1px solid #2b384b;border-radius:7px;outline:0;}
QListWidget::item{padding:8px;} QListWidget::item:selected{background:#294e51;color:white;}
QSlider::groove:horizontal{height:5px;background:#344259;border-radius:2px;} QSlider::sub-page:horizontal{background:#45c6a7;}
QSlider::handle:horizontal{background:#e9fff9;border-radius:7px;width:14px;margin:-5px 0;}
QComboBox{background:#263348;padding:7px;border:1px solid #35445b;border-radius:6px;}
QProgressBar{border:0;background:#263348;border-radius:5px;text-align:center;} QProgressBar::chunk{background:#38b998;border-radius:5px;}
QTabWidget::pane{border:0;} QTabBar::tab{background:#263348;padding:9px 14px;} QTabBar::tab:selected{background:#246255;color:#ffffff;} QScrollArea{border:0;} QToolTip{background:#263348;color:white;padding:6px;}
'''
class Studio(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('Yaser Studio AI '+updater.VERSION+' — استوديو ياسر');self.resize(1440,930);self.setWindowIcon(QIcon(str(engine.ROOT/'assets/yaser.ico')))
        self.states={};self.history={};self.current=None;self.original=None;self.preview=None;self.pending=[];self.output='';self.loading=False
        self.update_settings=QSettings('YaserStudioAI','Updates');
        if '--smoke-test' not in sys.argv and not os.environ.get('YASER_DISABLE_UPDATE_CHECK'):QTimer.singleShot(6000,lambda:self.check_online(True))
        self.pool=QThreadPool();self.pool.setMaxThreadCount(1);self.jobs=set();self.revision=0;self.busy=False;self.cancel=threading.Event()
        self.timer=QTimer();self.timer.setSingleShot(True);self.timer.setInterval(400);self.timer.timeout.connect(self.request_preview)
        central=QWidget();self.setCentralWidget(central);root=QVBoxLayout(central);root.setContentsMargins(22,18,22,16)
        header=QHBoxLayout();brand=QLabel('Yaser Studio AI');brand.setObjectName('brand');header.addWidget(brand)
        sub=QLabel('استوديو الصور  /  معالجة محلية على جهازك');sub.setObjectName('muted');header.addWidget(sub);header.addStretch();self.add_button(header,'تحديث من ملف',self.install_update);self.add_button(header,'تحديثات الإنترنت',self.configure_updates);root.addLayout(header)
        toolbar=QHBoxLayout();root.addLayout(toolbar)
        self.add_button(toolbar,'استيراد صور JPG',self.import_files,True)
        self.add_button(toolbar,'استيراد مجلد',self.import_folder)
        self.add_button(toolbar,'حفظ جلسة',self.save_session);self.add_button(toolbar,'فتح جلسة',self.load_session)
        toolbar.addStretch();self.add_button(toolbar,'تراجع',self.undo);self.add_button(toolbar,'ملاءمة الصورة',lambda:self.canvas.fit())
        self.compare=self.add_button(toolbar,'اضغط لعرض الأصل',lambda:None);self.compare.pressed.connect(self.show_original);self.compare.released.connect(self.show_preview)
        split=QSplitter();root.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left);left.setMinimumWidth(200);left.setMaximumWidth(290)
        label=QLabel('صور الدفعة');label.setObjectName('section');ll.addWidget(label)
        self.files=QListWidget();self.files.currentItemChanged.connect(self.select_item);ll.addWidget(self.files)
        self.count=QLabel('لا توجد صور');self.count.setObjectName('muted');ll.addWidget(self.count)
        self.add_button(ll,'إفراغ القائمة',self.clear_files)
        split.addWidget(left)
        mid=QWidget();ml=QVBoxLayout(mid);self.canvas=Canvas();self.canvas.stroke.connect(self.on_stroke);ml.addWidget(self.canvas,1)
        self.image_info=QLabel('ابدأ باستيراد صورة أو مجلد صور');self.image_info.setAlignment(Qt.AlignmentFlag.AlignCenter);ml.addWidget(self.image_info)
        tip=QLabel('عجلة الماوس للتكبير • السحب للتحريك في أداة العرض • المعاينة مخفّضة والحفظ بالدقة الأصلية');tip.setObjectName('muted');tip.setWordWrap(True);ml.addWidget(tip);split.addWidget(mid)
        panel=QWidget();panel.setMinimumWidth(360);panel.setMaximumWidth(470);outer=QVBoxLayout(panel);tabs=QTabWidget();tabs.setTabPosition(QTabWidget.TabPosition.North);outer.addWidget(tabs)
        quality_tab=QWidget();tabs.addTab(quality_tab,'١ الجودة');pl=QVBoxLayout(quality_tab);self.section(pl,'تحسين جودة الصورة')
        self.enhance_sliders={}
        for key,name in [('denoise','إزالة التشويش'),('sharpen','استرجاع الحدة')]:self.enhance_sliders[key]=self.control_slider(pl,name,0,100)
        row=QHBoxLayout();row.addWidget(QLabel('رفع الدقة عند الحفظ'));self.upscale=QComboBox();self.upscale.addItems(['الحجم الأصلي','تكبير ×2','تكبير ×4']);self.upscale.currentIndexChanged.connect(self.settings_changed);row.addWidget(self.upscale);pl.addLayout(row)
        note=QLabel('الحفظ ×2 أو ×4 يستخدم تكبير محلي محافظ ويحافظ على بنية الصورة.');note.setObjectName('muted');note.setWordWrap(True);pl.addWidget(note);pl.addStretch()

        color_tab=QWidget();tabs.addTab(color_tab,'٢ الضوء');pl=QVBoxLayout(color_tab);self.section(pl,'الإضاءة والألوان')
        self.tone_sliders={}
        tone_names=[('exposure','التعريض'),('contrast','التباين'),('highlights','الإضاءة القوية'),('shadows','الظلال'),('whites','الأبيض'),('blacks','الأسود'),('temperature','حرارة اللون'),('tint','صبغة اللون'),('vibrance','حيوية الألوان'),('saturation','التشبّع'),('clarity','الوضوح'),('dehaze','إزالة الضباب')]
        for key,name in tone_names:self.tone_sliders[key]=self.control_slider(pl,name,-100,100)
        self.section(pl,'تعديل موضعي بالفرشاة');self.local_kind=QComboBox();self.local_kind.addItems(['تفتيح','تغميق','تقوية اللون','تنعيم موضعي']);pl.addWidget(self.local_kind);self.local_amount=self.control_slider(pl,'قوة الفرشاة',1,100,35)

        skin_tab=QWidget();tabs.addTab(skin_tab,'٣ البورتريه');pl=QVBoxLayout(skin_tab);self.section(pl,'قوالب تنقية سريعة')
        self.preset=QComboBox();self.preset.addItems(['يدوي','طبيعي خفيف','استوديو متوازن','زفاف ناعم','تنظيف قوي','الحفاظ على النمش']);self.preset.currentIndexChanged.connect(self.preset_changed);pl.addWidget(self.preset)
        self.sliders=[]
        for name in ['الحبوب','التجاعيد','النمش / الشوائب','تنعيم البشرة']:self.sliders.append(self.control_slider(pl,name,0,100))
        self.portrait_sliders={}
        for key,name in [('skin_light','تفتيح البشرة'),('skin_tone','دفء لون البشرة'),('shine','إزالة اللمعان'),('under_eyes','الهالات تحت العين'),('eyes','تفتيح العيون'),('teeth','تبييض الأسنان')]:self.portrait_sliders[key]=self.control_slider(pl,name,0,100)
        self.add_button(pl,'تطبيق كل الإعدادات على الدفعة',self.apply_all,True)

        region_tab=QWidget();tabs.addTab(region_tab,'٤ الرتوش');pl=QVBoxLayout(region_tab);self.section(pl,'الوجوه والمناطق')
        self.face_list=QListWidget();self.face_list.setMaximumHeight(112);self.face_list.itemChanged.connect(self.face_changed);pl.addWidget(self.face_list)
        self.show_boxes=QCheckBox('إظهار إطارات الوجوه');self.show_boxes.setChecked(True);self.show_boxes.toggled.connect(self.show_preview);pl.addWidget(self.show_boxes)
        self.show_skin=QCheckBox('إظهار منطقة تنقية البشرة');self.show_skin.toggled.connect(self.show_preview);pl.addWidget(self.show_skin)
        self.mode=QComboBox();self.mode.addItems(['عرض وتحريك','إضافة منطقة بشرة','استثناء منطقة بشرة','إزالة عيب أو عنصر','تفتيح بالفرشاة','تغميق بالفرشاة','تقوية لون بالفرشاة','تنعيم بالفرشاة','استرجاع من الخلفية','حذف من الخلفية']);self.mode.currentIndexChanged.connect(self.mode_changed);pl.addWidget(self.mode)
        pl.addWidget(QLabel('حجم الفرشاة'));bs=QSlider(Qt.Orientation.Horizontal);bs.setRange(3,180);bs.setValue(25);bs.valueChanged.connect(lambda v:setattr(self.canvas,'brush',v));pl.addWidget(bs)
        self.add_button(pl,'إزالة العنصر المحدد',self.commit_removal)
        self.add_button(pl,'مسح تحديد الإزالة',self.clear_pending)
        pl.addStretch();bg_tab=QWidget();tabs.addTab(bg_tab,'٥ الخلفية');pl=QVBoxLayout(bg_tab);self.section(pl,'قص احترافي وتغيير الخلفية')
        self.add_button(pl,'اختيار خلفية من الكمبيوتر',self.choose_background)
        self.bg_label=QLabel('الخلفية الأصلية');self.bg_label.setWordWrap(True);self.bg_label.setObjectName('muted');pl.addWidget(self.bg_label)
        self.add_button(pl,'تطبيق الخلفية على الدفعة',self.background_all)
        self.add_button(pl,'استعادة الخلفية الأصلية',self.clear_background)
        self.background_sliders={}
        self.background_sliders['edge']=self.control_slider(pl,'إزاحة الحافة',-10,10,-2)
        self.background_sliders['feather']=self.control_slider(pl,'نعومة الحافة',0,20,2)
        self.background_sliders['decontaminate']=self.control_slider(pl,'تنظيف لون الخلفية القديمة',0,100,65)
        self.background_sliders['blur']=self.control_slider(pl,'ضبابية الخلفية الجديدة',0,100,0)
        note=QLabel('استخدم «استرجاع من الخلفية» للشعر أو الأطراف الناقصة، و«حذف من الخلفية» لبقايا الخلفية القديمة.');note.setWordWrap(True);note.setObjectName('muted');pl.addWidget(note)
        pl.addStretch();scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(panel);split.addWidget(scroll);split.setSizes([220,780,330])
        foot=QHBoxLayout();root.addLayout(foot);self.add_button(foot,'اختيار مجلد الإخراج',self.choose_output)
        self.output_label=QLabel('لم يُحدد مجلد الحفظ');self.output_label.setObjectName('muted');foot.addWidget(self.output_label,1)
        self.fmt=QComboBox();self.fmt.addItems(['JPG — جودة 98','PNG — بدون فقد']);foot.addWidget(self.fmt)
        self.add_button(foot,'حفظ الصورة الحالية',lambda:self.export(False));self.add_button(foot,'حفظ الدفعة كاملة',lambda:self.export(True),True)
        self.stop=self.add_button(foot,'إيقاف',self.cancel.set);self.stop.setEnabled(False)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);root.addWidget(self.progress)
        self.status=QLabel('جاهز • الصور الأصلية لا تُعدّل • لا تُرسل الصور إلى الإنترنت');root.addWidget(self.status)
        QShortcut(QKeySequence('Ctrl+Z'),self,activated=self.undo)
    def add_button(self,layout,title,fn,primary=False):
        b=QPushButton(title);b.clicked.connect(fn)
        if primary:b.setObjectName('primary')
        layout.addWidget(b);return b
    def section(self,layout,title):
        l=QLabel(title);l.setObjectName('section');layout.addWidget(l)
    def control_slider(self,layout,title,minimum,maximum,value=0):
        row=QHBoxLayout();row.addWidget(QLabel(title));number=QLabel(str(value));row.addStretch();row.addWidget(number);layout.addLayout(row)
        slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(minimum,maximum);slider.setValue(value);slider.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        slider.valueChanged.connect(number.setNum);slider.sliderPressed.connect(self.checkpoint);slider.valueChanged.connect(self.settings_changed);layout.addWidget(slider);return slider
    def run_job(self,fn,done,silent=False):
        j=Job(fn);self.jobs.add(j)
        def success(value):
            self.jobs.discard(j);self.centralWidget().setEnabled(True);done(value)
        def failure(error):
            self.jobs.discard(j)
            if silent:return
            self.centralWidget().setEnabled(True);self.busy=False;self.stop.setEnabled(False);self.status.setText('تعذرت العملية. راجع التفاصيل ثم حاول مجدداً.')
            if silent:return
            box=QMessageBox(self);box.setWindowTitle('تعذرت المعالجة');box.setText('لم تكتمل العملية؛ الصور الأصلية لم تتغير.');box.setDetailedText(error);box.exec()
        j.signals.done.connect(success);j.signals.error.connect(failure);j.signals.progress.connect(self.on_progress);self.pool.start(j)
    def on_progress(self,value,label):self.progress.setValue(value);self.status.setText(label)
    def import_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'استيراد الصور','','صور JPG (*.jpg *.jpeg *.JPG *.JPEG)');self.add_paths(paths)
    def import_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'اختر مجلد الصور')
        if folder:self.add_paths([str(p) for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in ('.jpg','.jpeg')])
    def add_paths(self,paths):
        for path in paths:
            path=str(Path(path).resolve())
            if path in self.states:continue
            self.states[path]=engine.fresh_state();self.history[path]=[]
            item=QListWidgetItem(Path(path).name);item.setData(Qt.ItemDataRole.UserRole,path);item.setToolTip(path);self.files.addItem(item)
        self.count.setText(f'{len(self.states)} صورة')
        if self.current is None and self.files.count():self.files.setCurrentRow(0)
    def clear_files(self):
        if self.busy:return
        if self.states and QMessageBox.question(self,'إفراغ القائمة','إزالة الصور والتعديلات من هذه الجلسة؟ احفظ الجلسة أولاً إن أردت العودة إليها.')!=QMessageBox.StandardButton.Yes:return
        self.revision+=1;self.current=None;self.files.clear();self.states.clear();self.history.clear();self.pending=[];self.original=None;self.preview=None;self.canvas.scene().clear();self.canvas.pix=None;self.face_list.clear();self.count.setText('لا توجد صور')
    def select_item(self,item,old):
        if not item:return
        self.current=item.data(Qt.ItemDataRole.UserRole);self.pending=[];self.original=None;self.preview=None;self.canvas.scene().clear();self.canvas.pix=None;self.canvas.zoomed=False;self.sync_controls();self.request_preview()
    def sync_controls(self):
        if not self.current:return
        self.loading=True;s=engine.normalize_state(self.states[self.current]);self.states[self.current]=s
        for slider,value in zip(self.sliders,s['settings']):slider.setValue(value)
        for key,slider in self.enhance_sliders.items():slider.setValue(s['enhance'][key])
        self.upscale.setCurrentIndex({1:0,2:1,4:2}.get(s['enhance'].get('upscale',1),0))
        for key,slider in self.tone_sliders.items():slider.setValue(s['tone'][key])
        for key,slider in self.portrait_sliders.items():slider.setValue(s['portrait'][key])
        for key,slider in self.background_sliders.items():slider.setValue(s['background_options'][key])
        self.preset.setCurrentText(s.get('preset','يدوي'))
        self.face_list.clear()
        for i,f in enumerate(s['faces'] or []):
            item=QListWidgetItem(f'الوجه {i+1}');item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if f['enabled'] else Qt.CheckState.Unchecked);self.face_list.addItem(item)
        if s['faces']==[]:self.face_list.addItem('لا وجوه مكتشفة — استخدم فرشاة البشرة')
        self.bg_label.setText(Path(s['background']).name if s['background'] else 'الخلفية الأصلية');self.loading=False
    def checkpoint(self,*args):
        if self.current and not self.loading:
            hist=self.history[self.current];hist.append(copy.deepcopy(self.states[self.current]));del hist[:-30]
    def settings_changed(self,*args):
        if self.loading or not self.current:return
        state=self.states[self.current];state['settings']=[s.value() for s in self.sliders]
        state['enhance']={key:slider.value() for key,slider in self.enhance_sliders.items()};state['enhance']['upscale']=[1,2,4][self.upscale.currentIndex()]
        state['tone']={key:slider.value() for key,slider in self.tone_sliders.items()};state['portrait']={key:slider.value() for key,slider in self.portrait_sliders.items()};state['background_options']={key:slider.value() for key,slider in self.background_sliders.items()};self.schedule()
    def preset_changed(self,*args):
        if self.loading or not self.current:return
        presets={
          'طبيعي خفيف':([25,15,15,22],{'skin_light':8,'skin_tone':4,'shine':20,'under_eyes':15,'eyes':10,'teeth':8}),
          'استوديو متوازن':([45,32,28,42],{'skin_light':12,'skin_tone':6,'shine':40,'under_eyes':30,'eyes':22,'teeth':18}),
          'زفاف ناعم':([52,38,35,55],{'skin_light':18,'skin_tone':8,'shine':48,'under_eyes':35,'eyes':28,'teeth':30}),
          'تنظيف قوي':([78,62,60,68],{'skin_light':15,'skin_tone':5,'shine':65,'under_eyes':52,'eyes':25,'teeth':25}),
          'الحفاظ على النمش':([38,22,0,32],{'skin_light':8,'skin_tone':5,'shine':30,'under_eyes':22,'eyes':15,'teeth':12})}
        name=self.preset.currentText();self.states[self.current]['preset']=name
        if name in presets:
            self.checkpoint();values,portrait=presets[name];self.loading=True
            for slider,value in zip(self.sliders,values):slider.setValue(value)
            for key,value in portrait.items():self.portrait_sliders[key].setValue(value)
            self.loading=False;self.settings_changed()
    def schedule(self):
        self.revision+=1;self.timer.start()
    def face_changed(self,item):
        if self.loading or not self.current:return
        row=self.face_list.row(item);faces=self.states[self.current]['faces'] or []
        if row>=len(faces):return
        self.checkpoint();faces[row]['enabled']=item.checkState()==Qt.CheckState.Checked;self.schedule()
    def mode_changed(self,i):self.canvas.set_mode(['view','skin','erase','remove','local_brighten','local_darken','local_saturate','local_smooth','bg_add','bg_erase'][i])
    def on_stroke(self,s):
        if not self.current:return
        if self.canvas.mode=='remove':self.pending.append(s);self.status.setText('تحديد إزالة جاهز — اضغط «إزالة العنصر المحدد»')
        elif self.canvas.mode.startswith('local_'):
            self.checkpoint();s['kind']=self.canvas.mode.removeprefix('local_');s['amount']=self.local_amount.value();self.states[self.current]['local_strokes'].append(s);self.schedule()
        elif self.canvas.mode.startswith('bg_'):
            self.checkpoint();s['erase']=self.canvas.mode=='bg_erase';self.states[self.current]['background_strokes'].append(s);self.schedule()
        else:self.checkpoint();self.states[self.current]['strokes'].append(s);self.schedule()
    def commit_removal(self):
        if not self.current or not self.pending:return
        self.checkpoint();self.states[self.current]['removals'].append(copy.deepcopy(self.pending));self.pending=[];self.schedule()
    def clear_pending(self):self.pending=[];self.show_preview()
    def undo(self):
        if not self.current:return
        if self.pending:self.pending.pop();self.show_preview();return
        if self.history[self.current]:self.states[self.current]=self.history[self.current].pop();self.sync_controls();self.schedule()
    def apply_all(self):
        if not self.current:return
        source=self.states[self.current]
        for p,s in self.states.items():
            self.history[p].append(copy.deepcopy(s));self.history[p]=self.history[p][-30:]
            for key in ('settings','enhance','tone','portrait','background_options','preset'):s[key]=copy.deepcopy(source[key])
        self.status.setText(f'تم تطبيق الجودة والإضاءة والألوان والتنقية على {len(self.states)} صورة؛ الفرشاة واختيار الوجوه يبقيان خاصين بكل صورة.');self.schedule()
    def choose_background(self):
        if not self.current:return
        p,_=QFileDialog.getOpenFileName(self,'اختيار الخلفية','','صور (*.jpg *.jpeg *.png *.webp *.bmp)')
        if p:self.checkpoint();self.states[self.current]['background']=p;self.sync_controls();self.schedule()
    def clear_background(self):
        if self.current:self.checkpoint();self.states[self.current]['background']=None;self.states[self.current]['background_strokes']=[];self.sync_controls();self.schedule()
    def background_all(self):
        if not self.current:return
        source=self.states[self.current];bg=source['background']
        for p,s in self.states.items():self.history[p].append(copy.deepcopy(s));self.history[p]=self.history[p][-30:];s['background']=bg;s['background_options']=copy.deepcopy(source['background_options'])
        self.status.setText('تم تطبيق اختيار الخلفية على الدفعة');self.schedule()
    def request_preview(self):
        if not self.current or self.busy:return
        self.revision+=1;revision=self.revision;path=self.current;state=engine.normalize_state(copy.deepcopy(self.states[path]));self.status.setText('جارٍ تجهيز المعاينة وكشف الوجوه…')
        def work(signals):
            if revision!=self.revision:return None
            rgb,_=engine.read_image(path,1400)
            if state['faces'] is None:state['faces']=engine.detect_faces(rgb)
            if revision!=self.revision:return None
            out=engine.process(rgb,state)
            return rgb,out,state['faces']
        def done(result):
            if result is None or revision!=self.revision or path!=self.current:return
            self.original,self.preview,faces=result
            if self.states[path]['faces'] is None:self.states[path]['faces']=faces
            self.sync_controls();self.show_preview()
            from PIL import Image
            with Image.open(path) as im:w,h=im.size
            self.image_info.setText(f'{Path(path).name}  •  {w} × {h}  •  {len(faces)} وجه')
            self.status.setText('المعاينة جاهزة • احفظ النسخة الجديدة عند الانتهاء')
        self.run_job(work,done)
    def show_original(self):
        if self.original is not None:self.canvas.show_image(self.original)
    def show_preview(self,*args):
        if self.preview is None:return
        display=self.preview
        if self.current and self.show_skin.isChecked():
            mask=engine.skin_mask(self.original,self.states[self.current])[...,None]*.35
            display=np.clip(display*(1-mask)+np.array([55,220,160])*mask,0,255).astype(np.uint8)
        self.canvas.show_image(display)
        if self.current and self.show_boxes.isChecked():self.canvas.draw_faces(self.states[self.current]['faces'])
        for s in self.pending:
            pts=s['points'];old=self.canvas.brush;self.canvas.brush=s['size']*1000
            for a,b in zip(pts,pts[1:] or pts):self.canvas.paint_segment(a,b)
            self.canvas.brush=old
    def choose_output(self):
        p=QFileDialog.getExistingDirectory(self,'مجلد إخراج واحد للدفعة')
        if p:self.output=p;self.output_label.setText(p)
    def export(self,all_images):
        if self.busy or not self.current:return
        if self.pending:
            QMessageBox.information(self,'تحديد غير مطبق','طبّق إزالة العنصر أو امسح تحديد الإزالة قبل الحفظ.');return
        if not self.output:self.choose_output()
        if not self.output:return
        paths=list(self.states) if all_images else [self.current];states=copy.deepcopy(self.states);folder=self.output;fmt='PNG' if self.fmt.currentIndex()==1 else 'JPG'
        self.timer.stop();self.revision+=1;self.busy=True;self.cancel.clear();self.stop.setEnabled(True);self.progress.setValue(0)
        def work(signals):
            saved=[];errors=[]
            for i,p in enumerate(paths):
                if self.cancel.is_set():break
                signals.progress.emit(round(i/len(paths)*100),f'معالجة {i+1} من {len(paths)} — {Path(p).name}')
                try:
                    rgb,meta=engine.read_image(p);s=states[p]
                    if s['faces'] is None:s['faces']=engine.detect_faces(rgb)
                    out=engine.process(rgb,s,final=True)
                    if self.cancel.is_set():break
                    saved.append(engine.save_new(out,p,folder,meta,fmt))
                    del rgb,out
                except Exception as e:errors.append(f'{p}: {e}')
            return saved,errors,self.cancel.is_set()
        def done(result):
            self.busy=False;self.stop.setEnabled(False);saved,errors,cancelled=result;self.progress.setValue(100 if not cancelled else self.progress.value())
            self.status.setText(f'تم حفظ {len(saved)} صورة جديدة • أخطاء: {len(errors)}'+(' • توقفت الدفعة' if cancelled else ''))
            box=QMessageBox(self);box.setWindowTitle('نتيجة الحفظ');box.setText(self.status.text()+f'\n{folder}')
            if errors:box.setDetailedText('\n'.join(errors))
            box.exec();self.request_preview()
        self.run_job(work,done)
    def save_session(self):
        if not self.states:return
        p,_=QFileDialog.getSaveFileName(self,'حفظ جلسة التعديلات','','جلسة ياسر (*.yaser.json)')
        if p:
            try:Path(p).write_text(json.dumps({'version':2,'states':self.states,'output':self.output},ensure_ascii=False),encoding='utf-8');self.status.setText('حُفظت الجلسة؛ أبقِ ملفات الصور والخلفيات في مواقعها')
            except Exception as e:QMessageBox.warning(self,'تعذر حفظ الجلسة',str(e))
    def load_session(self,preset=None):
        if self.busy:return
        p=preset if isinstance(preset,str) else QFileDialog.getOpenFileName(self,'فتح جلسة','','جلسة ياسر (*.json)')[0]
        if not p:return
        try:
            data=json.loads(Path(p).read_text(encoding='utf-8'));states=data['states']
            if data.get('version') not in (1,2) or not isinstance(states,dict):raise ValueError('صيغة جلسة غير مدعومة')
            for path,state in states.items():
                if len(state['settings'])!=4 or any(not isinstance(v,int) or not 0<=v<=100 for v in state['settings']):raise ValueError('مستويات غير صالحة')
                for key in ('strokes','removals'):assert isinstance(state[key],list)
                states[path]=engine.normalize_state(state)
            if self.states and QMessageBox.question(self,'فتح جلسة','استبدال الجلسة الحالية؟ تأكد من حفظها أولاً.')!=QMessageBox.StandardButton.Yes:return
            self.revision+=1;self.current=None;self.files.clear();self.states={};self.history={}
            existing={k:v for k,v in states.items() if Path(k).is_file()};self.add_paths(existing)
            self.states.update(existing);self.output=data.get('output','');self.output_label.setText(self.output or 'لم يُحدد مجلد الحفظ');self.sync_controls();self.request_preview()
            if len(existing)!=len(states):QMessageBox.information(self,'صور غير موجودة',f'تعذر العثور على {len(states)-len(existing)} صورة في موقعها السابق.')
        except Exception as e:QMessageBox.warning(self,'تعذر فتح الجلسة',str(e))
    def configure_updates(self):
        if self.jobs or self.busy:return
        value,ok=QInputDialog.getText(self,'تحديثات الإنترنت','رابط مستودع GitHub العام للإصدارات. يُفحص عند التشغيل؛ التنزيل والتثبيت بموافقتك. امسح الحقل لإيقاف الفحص.',text=self.update_settings.value('repository',updater.DEFAULT_REPO))
        if not ok:return
        if not value.strip():self.update_settings.setValue('repository','');self.status.setText('تم إيقاف فحص التحديثات عبر الإنترنت');return
        try:repo=updater.repository(value)
        except ValueError as e:QMessageBox.warning(self,'رابط غير صالح',str(e));return
        self.update_settings.setValue('repository',repo);self.check_online(False)
    def check_online(self,automatic=False):
        repo=self.update_settings.value('repository',updater.DEFAULT_REPO)
        if not repo or self.jobs or self.busy or self.timer.isActive():return
        def done(release):
            if automatic and (self.busy or self.jobs):return
            if release is None:
                if not automatic:QMessageBox.information(self,'التحديثات','أنت تستخدم أحدث إصدار منشور.');return
                return
            if QMessageBox.question(self,'تحديث جديد',f"الإصدار {release['version']} متاح من {repo}. تنزيله وتثبيته مع نقل الجلسة الحالية؟")!=QMessageBox.StandardButton.Yes:return
            if self.pending:QMessageBox.information(self,'تحديد غير مطبق','طبّق تحديد الإزالة أو امسحه قبل التحديث.');return
            destination=None
            if not release.get('installer'):
                destination=QFileDialog.getExistingDirectory(self,'مكان حفظ النسخة الجديدة')
                if not destination:return
            session={'version':2,'states':copy.deepcopy(self.states),'output':self.output};self.centralWidget().setEnabled(False)
            def work(signals):
                if release.get('installer'):return updater.stage_installer(release,session,signals.progress.emit)
                import tempfile
                with tempfile.TemporaryDirectory(prefix='Yaser-download-') as temp:
                    archive=updater.download(release,temp,signals.progress.emit)
                    return updater.install(archive,destination,session,signals.progress.emit)
            self.run_job(work,self.launch_updated)
        self.run_job(lambda signals:updater.latest(repo),done,silent=automatic)
    def launch_updated(self,folder):
        if isinstance(folder,dict):
            try:updater.start_installer(folder)
            except Exception as e:QMessageBox.warning(self,'تعذر بدء التحديث',str(e));return
            self.update_exit=True;QApplication.instance().quit();return
        try:
            env=os.environ.copy();env['PYINSTALLER_RESET_ENVIRONMENT']='1';env.pop('_MEIPASS2',None)
            subprocess.Popen([str(folder/'YaserStudioAI.exe'),'--resume-session',str(folder/'continued-session.yaser.json')],cwd=str(folder),env=env)
        except Exception as e:
            QMessageBox.warning(self,'تعذر فتح النسخة الجديدة',f'تم تجهيزها في {folder}. يمكنك فتحها يدوياً.\n{e}');return
        self.update_exit=True;QApplication.instance().quit()
    def install_update(self):
        if self.jobs or self.timer.isActive() or self.busy:
            QMessageBox.information(self,'تثبيت تحديث','انتظر اكتمال المعالجة الحالية ثم اضغط تثبيت تحديث.');return
        if self.pending:
            QMessageBox.information(self,'تحديد غير مطبق','طبّق تحديد الإزالة أو امسحه قبل التحديث.');return
        archive,_=QFileDialog.getOpenFileName(self,'اختر حزمة تحديث ياسر','','تحديث ياسر (*.exe *.zip)')
        if not archive:return
        if QMessageBox.question(self,'تثبيت تحديث','سيحفظ البرنامج جلستك ثم يثبت التحديث ويعيد فتحها. المثبّت يحدّث نفس مكان التثبيت والاختصار. اختر فقط حزمة حصلت عليها من مصدر تثق به؛ فحص سلامة الملفات لا يثبت هوية ناشرها. هل تريد المتابعة؟')!=QMessageBox.StandardButton.Yes:return
        if Path(archive).suffix.lower()=='.exe':
            session={'version':2,'states':copy.deepcopy(self.states),'output':self.output};self.centralWidget().setEnabled(False)
            self.run_job(lambda signals:updater.stage_installer(None,session,signals.progress.emit,local_file=archive),self.launch_updated);return
        destination=QFileDialog.getExistingDirectory(self,'اختر مكان حفظ النسخة الجديدة')
        if not destination:return
        session={'version':2,'states':copy.deepcopy(self.states),'output':self.output}
        self.centralWidget().setEnabled(False)
        def work(signals):return updater.install(archive,destination,session,signals.progress.emit)
        self.run_job(work,self.launch_updated)
    def closeEvent(self,event):
        if getattr(self,'update_exit',False) or '--smoke-test' in sys.argv:event.accept();return
        if self.jobs:
            self.cancel.set();QMessageBox.information(self,'العملية قيد التنفيذ','تم طلب الإيقاف. انتظر اكتمال الصورة الحالية ثم أغلق البرنامج.');event.ignore();return
        if self.states and QMessageBox.question(self,'إغلاق الاستوديو','إغلاق البرنامج؟ احفظ جلسة التعديلات أولاً إذا أردت الرجوع إليها.')!=QMessageBox.StandardButton.Yes:event.ignore();return
        event.accept()

def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs);QLocale.setDefault(QLocale('ar_IQ'))
    app=QApplication(sys.argv);translator=QTranslator(app);translator.load(str(engine.ROOT/'fonts'/'qtbase_ar.qm'));app.installTranslator(translator);QFontDatabase.addApplicationFont(str(engine.ROOT/'fonts'/'NotoSansArabic.ttf'));app.setFont(QFont('Noto Sans Arabic',10));app.setLayoutDirection(Qt.LayoutDirection.RightToLeft);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    app.setApplicationName('Yaser Studio AI');window=Studio();window.show()
    if '--resume-session' in sys.argv:
        QTimer.singleShot(0,lambda:window.load_session(sys.argv[sys.argv.index('--resume-session')+1]))
    if '--smoke-test' in sys.argv:
        QTimer.singleShot(1200,lambda:(window.grab().save(str(Path(sys.argv[sys.argv.index('--smoke-test')+1]))),app.quit()))
    return app.exec()
if __name__=='__main__':
    if '--engine-test' in sys.argv:
        try:
            rgb,meta=engine.read_image(sys.argv[2]);faces=engine.detect_faces(rgb);alpha=engine.person_alpha(rgb)
            state=engine.fresh_state();state['faces']=faces;state['settings']=[40,40,40,40]
            out=engine.process(rgb,state)
            report={'faces':len(faces),'shape':list(out.shape),'alpha_min':float(alpha.min()),'alpha_max':float(alpha.max()),'frozen':bool(getattr(sys,'frozen',False))}
            assert faces and out.shape==rgb.shape and alpha.max()>.9
            Path(sys.argv[3]).write_text(json.dumps(report),encoding='utf-8')
        except Exception:
            Path(sys.argv[3]).write_text(traceback.format_exc(),encoding='utf-8');sys.exit(1)
    else:sys.exit(main())
