class PaymentResponseParser:
    @staticmethod
    def response_to_json(response):
        key_pair_list = response.split('&')
        json_data = {each.split('=')[0]: each.split('=')[1] for each in key_pair_list}
        return json_data
