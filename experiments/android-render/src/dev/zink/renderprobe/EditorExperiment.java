package dev.zink.renderprobe;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.graphics.*;
import android.media.ExifInterface;
import android.net.Uri;
import android.util.Log;
import android.util.Size;
import android.view.View;
import android.view.ContextThemeWrapper;
import android.widget.ImageView;
import java.util.concurrent.atomic.AtomicReference;
import java.io.*;
import java.lang.reflect.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.*;

/** Calls editor methods in original DEX with synthetic local files only. */
public final class EditorExperiment {
    private static Class<?> c(ClassLoader l,String n) throws Exception {return Class.forName(n,true,l);}
    private static Object field(Object obj,String name) throws Exception {
        Field f=obj.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(obj);
    }
    private static void flushMain(Activity activity) throws Exception {
        CountDownLatch done=new CountDownLatch(1);activity.runOnUiThread(done::countDown);
        if(!done.await(10,TimeUnit.SECONDS)) throw new IOException("Main-thread timeout");
    }
    private static void copy(File input,File output) throws Exception {
        try(InputStream in=new FileInputStream(input);OutputStream out=new FileOutputStream(output)) {
            byte[] block=new byte[65536];int n;while((n=in.read(block))!=-1)out.write(block,0,n);
        }
    }
    private static void save(Bitmap b,File f) throws Exception {
        try(FileOutputStream out=new FileOutputStream(f)){b.compress(Bitmap.CompressFormat.PNG,100,out);}
    }
    private static Bitmap pattern(int w,int h) {
        Bitmap b=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(b);Paint p=new Paint();
        int[] colors={Color.RED,Color.GREEN,Color.BLUE,Color.YELLOW};
        for(int i=0;i<4;i++){p.setColor(colors[i]);canvas.drawRect((i%2)*w/2,(i/2)*h/2,(i%2+1)*w/2,(i/2+1)*h/2,p);}
        p.setColor(Color.BLACK);p.setTextSize(w/10f);canvas.drawText("TOP",w/10f,h/8f,p);
        return b;
    }
    public static void run(Activity activity,ClassLoader l,File out) throws Exception {
        Class<?> model=c(l,"com.hp.impulse.sprocket.viewmodel.DefaultPreviewFragmentViewModel");
        Class<?> image=c(l,"com.hp.impulse.sprocket.imagesource.ImageData");
        Method measure=model.getDeclaredMethod("performImageSizeMeasureWork",image,Size.class);measure.setAccessible(true);
        Method draw=model.getDeclaredMethod("drawChangesToFile",File.class,image);draw.setAccessible(true);
        Class<?> options=c(l,"com.hp.impulselib.device.SprocketDevice$Options");
        Object opts=options.getConstructor(c(l,"com.hp.impulselib.bt.SprocketBluetoothDevice")).newInstance(new Object[]{null});
        Object device=c(l,"com.hp.impulselib.device.GrandBahamaDevice").getConstructor(options).newInstance(opts);
        Class<?> base=c(l,"com.hp.impulse.sprocket.services.PreprocessPrintService");
        Object service=c(l,"com.hp.impulse.sprocket.services.BasicPrintService").getConstructor(Context.class,c(l,"com.hp.impulselib.device.SprocketDevice"),c(l,"com.hp.impulse.sprocket.services.PreprocessPrintService$PreprocessPrintServiceListener")).newInstance(activity,device,null);
        Class<?> data=c(l,"com.hp.impulse.sprocket.services.PreprocessPrintServiceData");
        Constructor<?> dc=data.getConstructor(image,c(l,"com.hp.impulse.sprocket.interfaces.ImageViewSource"),Bitmap.class,c(l,"com.hp.impulse.sprocket.model.EmbellishmentsMetricsData"));
        Method render=base.getDeclaredMethod("createPrintBitmap",data);render.setAccessible(true);
        JSONArray cases=new JSONArray();
        for(int[] dim:new int[][]{{1200,1800},{1800,1200},{1200,1200},{96,144},{1024,1536}}) {
            for(String action:new String[]{"identity","zoom-half","zoom-double","rotate90","pan-right"}) {
                one(activity,l,out,model,image,measure,draw,service,dc,render,cases,dim[0],dim[1],1,action);
            }
        }
        for(int[] dim:new int[][]{{1200,1800},{1800,1200},{1200,1200}})for(String action:new String[]{"fit-once","fit-twice"})one(activity,l,out,model,image,measure,draw,service,dc,render,cases,dim[0],dim[1],1,action);
        for(int orientation=2;orientation<=8;orientation++)one(activity,l,out,model,image,measure,draw,service,dc,render,cases,1200,1800,orientation,"identity");
    }
    private static JSONObject fitView(Activity activity,ClassLoader l,File out,String name,Object vm,Object im,File input,int count) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<Throwable> error=new AtomicReference<>();JSONObject report=new JSONObject();
        activity.runOnUiThread(()->{
            try {
                Context vendor=activity.createPackageContext("com.hp.impulse.sprocket",Context.CONTEXT_INCLUDE_CODE|Context.CONTEXT_IGNORE_SECURITY);
                int theme=vendor.getResources().getIdentifier("AppTheme","style","com.hp.impulse.sprocket");
                Context themed=new ContextThemeWrapper(vendor,theme);
                Class<?> viewType=c(l,"com.hp.impulse.sprocket.view.InteractiveImageView");
                ImageView view=(ImageView)viewType.getConstructor(Context.class).newInstance(themed);
                view.setBackgroundColor(Color.WHITE);
                view.measure(View.MeasureSpec.makeMeasureSpec(400,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(600,View.MeasureSpec.EXACTLY));view.layout(0,0,400,600);
                Bitmap bitmap=BitmapFactory.decodeFile(input.getPath());bitmap.setDensity(view.getResources().getDisplayMetrics().densityDpi);
                viewType.getMethod("updateOriginalFileSize",int.class,int.class).invoke(view,bitmap.getWidth(),bitmap.getHeight());
                Object imageType=c(l,"com.hp.impulse.sprocket.util.ImageUtil").getMethod("getImageDimensionType",int.class,int.class).invoke(null,bitmap.getWidth(),bitmap.getHeight());
                viewType.getMethod("setImageType",c(l,"com.hp.impulse.sprocket.view.InteractiveImageView$ImageType")).invoke(view,imageType);
                viewType.getMethod("setBaseRotated",boolean.class).invoke(view,bitmap.getWidth()>bitmap.getHeight());
                view.setImageBitmap(bitmap);
                JSONArray callbacks=new JSONArray();
                Class<?> listener=c(l,"com.hp.impulse.sprocket.view.InteractiveImageView$InteractiveImageViewInteractedListener");
                Object proxy=Proxy.newProxyInstance(l,new Class<?>[]{listener},(obj,method,args)->{
                    callbacks.put(method.getName());
                    if(method.getName().equals("onReset"))((Matrix)vm.getClass().getMethod("getPreviewMatrix").invoke(vm)).reset();
                    if(method.getName().equals("onScale"))vm.getClass().getMethod("onScale",float.class,float.class,float.class,Size.class,c(l,"com.hp.impulse.sprocket.imagesource.ImageData")).invoke(vm,args[0],args[1],args[2],new Size(400,600),im);
                    return null;
                });
                viewType.getMethod("setListener",listener).invoke(view,proxy);
                for(int i=0;i<count;i++)viewType.getMethod("fitOrFill").invoke(view);
                Bitmap snapshot=Bitmap.createBitmap(400,600,Bitmap.Config.ARGB_8888);view.draw(new Canvas(snapshot));save(snapshot,new File(out,name+"-preview.png"));snapshot.recycle();
                float[] values=new float[9];view.getImageMatrix().getValues(values);JSONArray matrix=new JSONArray();for(float v:values)matrix.put(v);
                report.put("matrix",matrix).put("callbacks",callbacks).put("baseRotationHint",viewType.getMethod("getBaseRotationHint").invoke(view));
                bitmap.recycle();
            }catch(Throwable e){error.set(e);}finally{done.countDown();}
        });
        if(!done.await(15,TimeUnit.SECONDS))throw new IOException("View test timed out");
        if(error.get()!=null)throw new RuntimeException(error.get());
        return report;
    }
    private static void one(Activity activity,ClassLoader l,File out,Class<?> model,Class<?> image,Method measure,Method draw,Object service,Constructor<?> dc,Method render,JSONArray cases,int w,int h,int orientation,String action) throws Exception {
        String name=w+"x"+h+"-exif"+orientation+"-"+action;
        JSONObject result=new JSONObject().put("case",name);
        try {
            File input=new File(out,name+"-input.jpg");Bitmap bitmap=pattern(w,h);
            try(FileOutputStream f=new FileOutputStream(input)){bitmap.compress(Bitmap.CompressFormat.JPEG,100,f);}bitmap.recycle();
            ExifInterface exif=new ExifInterface(input.getPath());exif.setAttribute(ExifInterface.TAG_ORIENTATION,Integer.toString(orientation));exif.saveAttributes();
            Object im=image.getConstructor(String.class,String.class).newInstance(Uri.fromFile(input).toString(),name);
            image.getMethod("setPhotofixApplied",boolean.class).invoke(im,true);
            Object vm=model.getConstructor(Application.class).newInstance(activity.getApplication());
            Size viewport=new Size(400,600);
            measure.invoke(vm,im,viewport);flushMain(activity);
            result.put("measuredWidth",field(vm,"width")).put("measuredHeight",field(vm,"height")).put("widthScale",field(vm,"widthScale")).put("heightScale",field(vm,"heightScale"));
            File measured=(File)field(vm,"transformedImageFile");
            if(measured==null)throw new IOException("No measured file");
            copy(measured,new File(out,name+"-measured.jpg"));
            if(action.startsWith("zoom"))model.getMethod("onScale",float.class,float.class,float.class,Size.class,image).invoke(vm,action.equals("zoom-half")?0.5f:2f,200f,300f,viewport,im);
            if(action.equals("rotate90"))model.getMethod("onRotate",float.class,float.class,float.class,Size.class,image).invoke(vm,90f,200f,300f,viewport,im);
            if(action.equals("pan-right"))model.getMethod("onTranslate",float.class,float.class,Size.class,image).invoke(vm,100f,0f,viewport,im);
            if(action.startsWith("fit-")) result.put("view",fitView(activity,l,out,name,vm,im,input,action.equals("fit-twice")?2:1));
            Matrix matrix=(Matrix)model.getMethod("getPreviewMatrix").invoke(vm);float[] values=new float[9];matrix.getValues(values);JSONArray m=new JSONArray();for(float v:values)m.put(v);result.put("matrix",m);
            draw.invoke(vm,measured,im);
            File edited=(File)image.getMethod("getTransformedBitmap").invoke(im);
            if(edited==null)throw new IOException("No transformed output");
            copy(edited,new File(out,name+"-edited.bin"));Bitmap editBitmap=BitmapFactory.decodeFile(edited.getPath());
            result.put("editedWidth",editBitmap.getWidth()).put("editedHeight",editBitmap.getHeight()).put("editedFileSuffix",edited.getName().substring(edited.getName().lastIndexOf('.')));
            save(editBitmap,new File(out,name+"-edited.png"));editBitmap.recycle();
            Bitmap finalBitmap=(Bitmap)render.invoke(service,dc.newInstance(im,null,null,null));
            result.put("finalWidth",finalBitmap.getWidth()).put("finalHeight",finalBitmap.getHeight());save(finalBitmap,new File(out,name+"-final.png"));finalBitmap.recycle();
        }catch(Throwable error){result.put("error",Log.getStackTraceString(error));}
        cases.put(result);Log.i("ZinkEditorResearch",result.toString());
        try(FileWriter f=new FileWriter(new File(out,"editor-results.json"))){f.write(cases.toString(2));}
    }
}
