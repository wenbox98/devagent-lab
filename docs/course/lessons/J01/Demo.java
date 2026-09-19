import java.util.concurrent.ConcurrentHashMap;

public class Demo {
    public static void main(String[] args) {
        var requests = new ConcurrentHashMap<String, String>();
        System.out.println(requests.putIfAbsent("user1:key1", "bodyA"));
        System.out.println(requests.putIfAbsent("user1:key1", "bodyA"));
        System.out.println(requests.putIfAbsent("user1:key1", "bodyB"));
        System.out.println(requests.get("user1:key1"));
    }
}
