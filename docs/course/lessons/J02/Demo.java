import java.util.concurrent.*;

public class Demo {
    public static void main(String[] args) throws Exception {
        var gate = new CountDownLatch(1);
        var pool = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(1), new ThreadPoolExecutor.AbortPolicy());
        Runnable slow = () -> {
            try { gate.await(); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        };
        int rejected = 0;
        try {
            pool.execute(slow);
            pool.execute(slow);
            try { pool.execute(slow); }
            catch (RejectedExecutionException e) { rejected++; }
            System.out.println("rejected=" + rejected);
        } finally {
            gate.countDown();
            pool.shutdown();
            pool.awaitTermination(2, TimeUnit.SECONDS);
        }
    }
}
