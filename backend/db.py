import psycopg2

class DatabaseInterface:
    def __init__(self, db_config):
        self.conn = psycopg2.connect(**db_config)

    def execute_query(self, query):
        cursor = self.conn.cursor()
        try:
            cursor.execute(query)

            column_names = [desc[0] for desc in cursor.description] if cursor.description else []

            try:
                result = cursor.fetchall()
            except psycopg2.ProgrammingError:
                result = None

            self.conn.commit()
            return result, column_names

        except Exception as e:
            self.conn.rollback()
            raise e

        finally:
            cursor.close()