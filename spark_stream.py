import logging
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, to_json, struct, from_unixtime
from cassandra.cluster import Cluster
from pyspark.sql.types import StructType, StructField, StringType

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s',
                    handlers=[logging.StreamHandler()])

def create_keyspace(session):
    session.execute("""
        CREATE KEYSPACE IF NOT EXISTS spark_streams
        WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '1'};
    """)
    logging.info("Keyspace created successfully!")

def create_table(session):
    session.execute("""
    CREATE TABLE IF NOT EXISTS spark_streams.created_users (
        id UUID PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        gender TEXT,
        address TEXT,
        post_code TEXT,
        email TEXT,
        username TEXT,
        dob TEXT,
        registered_date TEXT,
        phone TEXT,
        picture TEXT);
    """)
    logging.info("Table created successfully!")

def insert_data(session, **kwargs):
    user_id = kwargs.get('id')
    first_name = kwargs.get('first_name')
    last_name = kwargs.get('last_name')
    gender = kwargs.get('gender')
    address = kwargs.get('address')
    postcode = kwargs.get('post_code')
    email = kwargs.get('email')
    username = kwargs.get('username')
    dob = kwargs.get('dob')
    registered_date = kwargs.get('registered_date')
    phone = kwargs.get('phone')
    picture = kwargs.get('picture')

    try:
        session.execute("""
            INSERT INTO spark_streams.created_users(id, first_name, last_name, gender, address, 
                post_code, email, username, dob, registered_date, phone, picture)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, first_name, last_name, gender, address,
              postcode, email, username, dob, registered_date, phone, picture))
        logging.info(f"Data inserted for {first_name} {last_name}")

    except Exception as e:
        logging.error(f'Could not insert data due to {e}')

def create_spark_connection():
    try:
        s_conn = SparkSession.builder \
            .appName('SparkDataStreaming') \
            .config('spark.jars.packages', "com.datastax.spark:spark-cassandra-connector_2.13:3.5.2,"
                                           "org.apache.spark:spark-sql-kafka-0-10_2.13:3.5.2") \
            .config('spark.cassandra.connection.host', 'localhost') \
            .getOrCreate()

        s_conn.sparkContext.setLogLevel("ERROR")
        logging.info("Spark connection created successfully!")
        return s_conn
    except Exception as e:
        logging.error(f"Couldn't create the spark session due to exception {e}")
        return None

def connect_to_kafka(spark_conn):
    try:
        spark_df = spark_conn.readStream \
            .format('kafka') \
            .option('kafka.bootstrap.servers', 'localhost:9092') \
            .option('subscribe', 'users_created') \
            .option('startingOffsets', 'earliest') \
            .option('failOnDataLoss', 'false') \
            .load()
        logging.info("Kafka DataFrame created successfully")
        return spark_df
    except Exception as e:
        logging.error(f"Kafka DataFrame could not be created because: {e}")
        return None

def create_cassandra_connection():
    try:
        cluster = Cluster(['localhost'])
        cas_session = cluster.connect()
        return cas_session
    except Exception as e:
        logging.error(f"Could not create cassandra connection due to {e}")
        return None

def create_selection_df_from_kafka(spark_df):
    schema = StructType([
        StructField("id", StringType(), False),
        StructField("first_name", StringType(), False),
        StructField("last_name", StringType(), False),
        StructField("gender", StringType(), False),
        StructField("address", StringType(), False),
        StructField("post_code", StringType(), False),
        StructField("email", StringType(), False),
        StructField("username", StringType(), False),
        StructField("registered_date", StringType(), False),
        StructField("phone", StringType(), False),
        StructField("picture", StringType(), False)
    ])

    sel = spark_df.selectExpr("CAST(value AS STRING)") \
        .select(from_json(col('value'), schema).alias('data')).select("data.*")
    logging.info("Selection DataFrame created successfully!")
    return sel

def write_to_cassandra(selection_df):
    try:
        streaming_query = (selection_df.writeStream.format("org.apache.spark.sql.cassandra")
                           .option('checkpointLocation', '/tmp/checkpoint')
                           .option('keyspace', 'spark_streams')
                           .option('table', 'created_users')
                           .start())
        return streaming_query
    except Exception as e:
        logging.error(f"Couldn't write to cassandra table because {e}")
        return None

if __name__ == '__main__':
    spark = create_spark_connection()
    cas_session = create_cassandra_connection()
    create_keyspace(cas_session)
    create_table(cas_session)

    kafka_spark_df = connect_to_kafka(spark)
    if kafka_spark_df:
        selection_df = create_selection_df_from_kafka(kafka_spark_df)
        query = write_to_cassandra(selection_df)

        try:
            query.awaitTermination()
        except Exception as e:
            logging.error(f"Streaming stopped due to {e}")
