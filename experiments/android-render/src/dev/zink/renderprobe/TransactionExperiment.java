package dev.zink.renderprobe;

import java.io.*;
import org.json.*;

/** Original message serializers and transfer bookkeeping only. No controller/client. */
public final class TransactionExperiment {
    private static Class<?> cls(ClassLoader l,String n) throws Exception {return Class.forName("com.hp.impulselib."+n,true,l);}
    private static String serialize(ClassLoader l,Object obj) throws Exception {
        Class<?> b=cls(l,"HPLPP.SprocketByteBuffer");Object buf=b.getConstructor(int.class).newInstance(4096);
        obj.getClass().getMethod("serializeMessage",b).invoke(obj,buf);b.getMethod("flip").invoke(buf);
        StringBuilder s=new StringBuilder();for(byte v:(byte[])b.getMethod("copyRemainingData").invoke(buf))s.append(String.format(java.util.Locale.ROOT,"%02x",v&255));return s.toString();
    }
    public static void run(ClassLoader l,File out) throws Exception {
        JSONObject r=new JSONObject();r.put("transmitted",false);r.put("syntheticHandle",7);r.put("syntheticJobId",4660);
        Class<?> start=cls(l,"HPLPP.messages.PrintStartRequestMessage");Object st=start.getConstructor().newInstance();start.getMethod("setFileLength",int.class).invoke(st,139679);r.put("start",serialize(l,st));
        Class<?> prop=cls(l,"HPLPP.messages.model.JobProperty");Object p=prop.getConstructor(short.class).newInstance((short)0x1234);prop.getMethod("setNumCopies",int.class).invoke(p,1);prop.getMethod("setJobName",String.class).invoke(p,"SELECT-CAL-01");r.put("properties",serialize(l,cls(l,"HPLPP.messages.WriteJobPropertyRequestMessage").getConstructor(prop).newInstance(p)));
        byte[] data=new byte[17];for(int i=0;i<data.length;i++)data[i]=(byte)i;
        Class<?> tt=cls(l,"bt.hplpp.helpers.HPLPPTransferInfo$TransferType");Class<?> tr=cls(l,"bt.hplpp.helpers.HPLPPTransferInfo");Object transfer=tr.getConstructor(byte[].class,tt).newInstance(data,tt.getField("IMAGE").get(null));tr.getMethod("setPacketSize",int.class).invoke(transfer,8);
        JSONArray chunks=new JSONArray();Class<?> write=cls(l,"HPLPP.messages.FileWriteRequestMessage");
        for(int ack:new int[]{0,8,16}) {tr.getMethod("confirmPage",int.class).invoke(transfer,ack);int n=(Integer)tr.getMethod("getPacketSize").invoke(transfer);Object w=write.getConstructor().newInstance();write.getMethod("setFileHandle",byte.class).invoke(w,(byte)7);write.getMethod("setFileData",byte[].class,int.class,int.class).invoke(w,data,ack,n);chunks.put(new JSONObject().put("confirmedOffset",ack).put("payloadLength",n).put("message",serialize(l,w)).put("reportedProgress",tr.getMethod("getProgress").invoke(transfer)));}
        r.put("chunks",chunks);r.put("listJobs",serialize(l,cls(l,"HPLPP.messages.ListJobsRequestMessage").getConstructor().newInstance()));r.put("dropJob",serialize(l,cls(l,"HPLPP.messages.DropJobRequestMessage").getConstructor(short.class).newInstance((short)0x1234)));
        Class<?> buffer=cls(l,"HPLPP.SprocketByteBuffer");Class<?> rsp=cls(l,"HPLPP.messages.FileWriteResponseMessage");Object response=rsp.getConstructor().newInstance();Object bytes=buffer.getConstructor(byte[].class).newInstance((Object)new byte[]{7,2,17,0,0,0,17,0,0,0});rsp.getMethod("deserializeMessage",buffer).invoke(response,bytes);r.put("decodedCompletion",new JSONObject().put("handle",rsp.getMethod("getFileHandle").invoke(response)).put("status",rsp.getMethod("getStatus").invoke(response)).put("received",rsp.getMethod("getReceivedLength").invoke(response)).put("total",rsp.getMethod("getTotalLength").invoke(response)));
        try(FileWriter f=new FileWriter(new File(out,"transaction.json"))){f.write(r.toString(2));}
    }
}
