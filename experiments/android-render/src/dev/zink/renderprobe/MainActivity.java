package dev.zink.renderprobe;

import android.app.Activity;
import android.os.Bundle;
import android.content.Context;
import android.graphics.*;
import android.util.Log;
import android.widget.TextView;
import java.io.*;
import java.lang.reflect.*;
import org.json.*;

/** Offline harness invoking original vendor DEX; no transport objects are created. */
public final class MainActivity extends Activity {
    private ClassLoader vendor;
    private File out;
    private final JSONArray results = new JSONArray();
    private Class<?> type(String name) throws Exception { return Class.forName(name, true, vendor); }
    private void note(String msg) { Log.i("ZinkRenderResearch", msg); }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("Offline image-processing experiment. No printer connection.");
        setContentView(text);
        new Thread(() -> {
            try { runExperiment(); note("COMPLETE " + out); }
            catch (Throwable e) { Log.e("ZinkRenderResearch", "FAILED", e); }
        }, "offline-render").start();
    }
    private void saveBitmap(String name, Bitmap b) throws Exception {
        try (FileOutputStream f = new FileOutputStream(new File(out, name))) {
            b.compress(Bitmap.CompressFormat.PNG, 100, f);
        }
    }
    private Bitmap pattern(int w, int h) {
        Bitmap b = Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);
        int[] pixels = new int[w*h];
        for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
            int r = x*255/Math.max(1,w-1), g = y*255/Math.max(1,h-1);
            int blue = ((x/(Math.max(1,w/12)) + y/Math.max(1,h/12))%2)*160+40;
            pixels[y*w+x] = Color.rgb(r,g,blue);
        }
        b.setPixels(pixels,0,w,0,0,w,h);
        Canvas c=new Canvas(b); Paint p=new Paint();p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(Math.max(2,w/100));p.setColor(Color.MAGENTA);
        c.drawRect(1,1,w-1,h-1,p);
        return b;
    }
    private String serializeOffline(Object message) throws Exception {
        Class<?> bufferType=type("com.hp.impulselib.HPLPP.SprocketByteBuffer");
        Object buffer=bufferType.getConstructor(int.class).newInstance(512);
        message.getClass().getMethod("serializeMessage",bufferType).invoke(message,buffer);
        bufferType.getMethod("flip").invoke(buffer);
        byte[] bytes=(byte[])bufferType.getMethod("copyRemainingData").invoke(buffer);
        StringBuilder hex=new StringBuilder();
        for(byte b:bytes) hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return hex.toString();
    }
    private void inspectMessages() throws Exception {
        JSONObject report=new JSONObject();
        Class<?> startType=type("com.hp.impulselib.HPLPP.messages.PrintStartRequestMessage");
        Object start=startType.getConstructor().newInstance();
        startType.getMethod("setFileLength",int.class).invoke(start,42309);
        report.put("printStartFor42309Bytes",serializeOffline(start));
        Class<?> propType=type("com.hp.impulselib.HPLPP.messages.model.JobProperty");
        Object props=propType.getConstructor(short.class).newInstance((short)0x1234);
        props.getClass().getMethod("setNumCopies",int.class).invoke(props,1);
        props.getClass().getMethod("setJobName",String.class).invoke(props,"OFFLINE");
        Class<?> writeType=type("com.hp.impulselib.HPLPP.messages.WriteJobPropertyRequestMessage");
        report.put("syntheticJobProperties",serializeOffline(writeType.getConstructor(propType).newInstance(props)));
        report.put("transmitted",false);
        try(FileWriter f=new FileWriter(new File(out,"offline-messages.json"))){f.write(report.toString(2));}
        note("OFFLINE_MESSAGES "+report);
    }
    private void runExperiment() throws Exception {
        String runName=getIntent().getStringExtra("run");
        if(runName==null) runName="default";
        if(!runName.matches("[a-zA-Z0-9_-]+")) throw new IllegalArgumentException("Invalid run name");
        out=new File(getFilesDir(),"results-"+runName); out.mkdirs();
        Context vc=createPackageContext("com.hp.impulse.sprocket",Context.CONTEXT_INCLUDE_CODE|Context.CONTEXT_IGNORE_SECURITY);
        vendor=vc.getClassLoader();
        note("LOADER "+vendor);
        Class<?> options=type("com.hp.impulselib.device.SprocketDevice$Options");
        Object opts=options.getConstructor(type("com.hp.impulselib.bt.SprocketBluetoothDevice")).newInstance(new Object[]{null});
        Object device=type("com.hp.impulselib.device.GrandBahamaDevice").getConstructor(options).newInstance(opts);
        Class<?> base=type("com.hp.impulse.sprocket.services.PreprocessPrintService");
        Class<?> basic=type("com.hp.impulse.sprocket.services.BasicPrintService");
        Object service=basic.getConstructor(Context.class,type("com.hp.impulselib.device.SprocketDevice"),type("com.hp.impulse.sprocket.services.PreprocessPrintService$PreprocessPrintServiceListener")).newInstance(this,device,null);
        Class<?> data=type("com.hp.impulse.sprocket.services.PreprocessPrintServiceData");
        Class<?> image=type("com.hp.impulse.sprocket.imagesource.ImageData");
        Constructor<?> dc=data.getConstructor(image,type("com.hp.impulse.sprocket.interfaces.ImageViewSource"),Bitmap.class,type("com.hp.impulse.sprocket.model.EmbellishmentsMetricsData"));
        Method render=base.getDeclaredMethod("createPrintBitmap",data);render.setAccessible(true);
        Method quality=basic.getDeclaredMethod("getCompression");quality.setAccessible(true);
        int jpegQuality=(Integer)quality.invoke(service);
        Class<?> util=type("com.hp.impulse.sprocket.util.ImageUtil");
        Method compress=util.getMethod("compressBitmapsToJPEG",Bitmap.class,int.class);
        Class<?> fc=type("com.hp.impulse.sprocket.controller.FeaturesController");
        Object features=fc.getMethod("get").invoke(null);
        Class<?> featureEnum=type("com.hp.impulse.sprocket.controller.FeaturesController$Features");
        Object lanczos=featureEnum.getField("LANCZOS_ALGORITHM").get(null);
        boolean defaultLanczos=(Boolean)fc.getMethod("isLanczosAlgorithmEnabled",Context.class).invoke(features,this);
        note("DEFAULT_LANCZOS "+defaultLanczos);
        Method process=basic.getDeclaredMethod("processData",data,type("com.hp.impulse.sprocket.services.PreprocessPrintService$ProgressReporter"));process.setAccessible(true);
        JSONArray profiles=new JSONArray();
        Class<?> profilesClass=type("com.hp.impulselib.device.SprocketDeviceType");
        for(Object profile:profilesClass.getEnumConstants()) {
            Point point=(Point)profilesClass.getMethod("getPrintSize").invoke(profile);
            profiles.put(new JSONObject().put("name",profile.toString()).put("width",point.x).put("height",point.y).put("quality",profilesClass.getMethod("getPrintCompression").invoke(profile)));
        }
        try(FileWriter f=new FileWriter(new File(out,"profiles.json"))){f.write(profiles.toString(2));}
        inspectMessages();
        if(getIntent().getBooleanExtra("inspectOnly",false)) return;
        int[][] sizes={{768,1152},{1200,1200},{1600,900},{600,1800},{96,144},{1536,2304}};
        for(String route:new String[]{"override","file-lanczos","file-matrix"}) for(int[] s:sizes) for(boolean photoFix:new boolean[]{false,true}) {
            String name=route+"-"+s[0]+"x"+s[1]+(photoFix?"-photofix":"-plain");
            JSONObject result=new JSONObject();result.put("case",name);
            try {
                Bitmap input=pattern(s[0],s[1]);saveBitmap(name+"-input.png",input);
                Object im=image.getConstructor(String.class,String.class).newInstance("synthetic",name);
                image.getMethod("setPhotofixApplied",boolean.class).invoke(im,!photoFix);
                image.getMethod("setTransformedBitmap",File.class).invoke(im,new File(out,name+"-input.png"));
                fc.getMethod("setFeatureBoolean",Context.class,featureEnum,boolean.class).invoke(features,this,lanczos,!route.equals("file-matrix"));
                result.put("lanczosEnabled",fc.getMethod("isLanczosAlgorithmEnabled",Context.class).invoke(features,this));
                Object d=dc.newInstance(im,null,route.equals("override")?input:null,null);
                long start=System.nanoTime();
                Bitmap output=(Bitmap)render.invoke(service,d);
                result.put("milliseconds",(System.nanoTime()-start)/1000000);
                result.put("width",output.getWidth());result.put("height",output.getHeight());result.put("jpegQuality",jpegQuality);
                saveBitmap(name+"-output.png",output);
                byte[] bytes=(byte[])compress.invoke(null,output,jpegQuality);
                try(FileOutputStream f=new FileOutputStream(new File(out,name+".jpg"))){f.write(bytes);}
                result.put("jpegBytes",bytes.length);
                process.invoke(service,d,null);
                byte[] fullBytes=(byte[])data.getMethod("getPrintableBytes").invoke(d);
                result.put("processDataMatches",java.util.Arrays.equals(bytes,fullBytes));
                try(FileOutputStream f=new FileOutputStream(new File(out,name+"-process.jpg"))){f.write(fullBytes);}
                if(photoFix) {
                    Bitmap diagnostic=output.copy(Bitmap.Config.ARGB_8888,true);
                    Object pf=type("com.hp.photofix.PhotoFix").getConstructor().newInstance();
                    Class<?> mode=type("com.hp.photofix.PhotoFix$PhotoFixMode");
                    Field handle=pf.getClass().getDeclaredField("libHandle");handle.setAccessible(true);
                    result.put("photoFixHandleSign",Long.signum(handle.getLong(pf)));
                    result.put("photoFixDiagnosticResult",pf.getClass().getMethod("apply",Bitmap.class,Bitmap.class,mode).invoke(pf,diagnostic,diagnostic,mode.getField("DEFAULT_PHOTOFIX").get(null)).toString());
                    diagnostic.recycle();
                }
                output.recycle();input.recycle();
            } catch(Throwable e) {result.put("error",Log.getStackTraceString(e));}
            results.put(result);note(result.toString());
            try(FileWriter f=new FileWriter(new File(out,"results.json"))){f.write(results.toString(2));}
        }
    }
}
